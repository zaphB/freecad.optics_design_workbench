__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


try:
  import FreeCADGui as Gui
  import FreeCAD as App
  from FreeCAD import Vector
except ImportError:
  pass

from numpy import *
import time
import sympy as sy
import functools
import re

from .. import io
from .. import simulation
from .. import distributions

_LAST_PROCESS_EVENTS_CALL = time.time()

# global dict with keys being proxy objects and values being 
# more dicts that store pseudo-attributes. This awkward attribute storing
# format allows to bypass the serializer which wants to save the Proxy
# objects whenever the FreeCAD project is saved.
NON_SERIALIZABLE_STORE = {}


###################################################################################
# PLACEMENT PATH RESOLVER

def allPlacementsAndPaths(obj, ignoreLinks=False, _recDepth=0):
  '''
  For the given obj return a list with one entry for each representation the obj's
  Shape exists in the global CAD model of the document.
  Each entry is a (placement,path) tuple, where path is a dot separated
  path and placement is the placement transform of this path. In principle an entry
  can have more than one of such entries.
  '''
  # raise if recursion depth gets out of hand
  if _recDepth > 100:
    raise RuntimeError(f'allPlacementsAndPaths reached recursion depth {_recDepth}')

  # prepare result and parents lists
  result = []
  parents = obj.Parents

  # no parents means this object lives in the toplevel of the document and no
  # links point to it indirectly -> return identity placement
  if not len(parents):
    #print(f'{str(obj.Document):<20} -> {obj} has no parents')
    result = [[(obj.Placement, obj.Name)]]
  else:
    #print(f'{str(obj.Document):<20} -> {obj} has parents {parents}')
    pass

  for parentObj, path in parents:
    # if parentObj is not in this document -> do not add it
    if parentObj.Document != simulation.simulatingDocument():
      #print(f'skipping {parentObj=} from document {parentObj.Document}')
      continue

    # get placement matrix up to parent that we just found 
    parentPlacement = parentObj.getSubObject(path, retType=3)

    # recursively find placements of each parentObj and modify all results we collected so far
    #print(f'{str(parentObj.Document):<20} -> {parentObj} resolving great parents...')
    for greatParents in allPlacementsAndPaths(parentObj, _recDepth=_recDepth+1):
      result.append( greatParents+[(parentPlacement, parentObj.Name+'.'+path)] )

  if not ignoreLinks:
    for link in [o for o in obj.InList if o.isDerivedFrom('App::Link')]: 
      # only add links that live in current document
      if link.Document != simulation.simulatingDocument():
        result.extend( allPlacementsAndPaths(link, ignoreLinks=ignoreLinks, _recDepth=_recDepth+1 ) )
  
  # in deeper rec depths: return list of results as is, only do further cleanup if 
  # in outermost rec level
  if _recDepth > 0:
    return result

  # clean up path overlaps (typical for parents and grandparents)
  _result = []
  for r in result:
    # make sure paths have no trailing or leading dots
    r = [(pl, '.'.join([e for e in path.split('.') if e.strip()]))
                                                  for pl, path in r]

    _result.append([])
    prevP = None
    for p in r:
      # path of grandparent exactly matches start of following path? -> remove grandparent
      if prevP is not None and not p[1].startswith(prevP[1]):
        _result[-1].append(prevP)
      prevP = p
    _result[-1].append(p)

  # keep only last placement entry in each path resolution list, merge all object name paths
  _result = [ ( [m for m,_ in r][-1], '.'.join([p for _,p in r]) ) for r in _result ]
  
  # sort lexically by paths
  _result = sorted( _result, key=lambda e: e[1] )

  # return cleaned result list
  return _result


def allCoordinateTransformMatrices(obj, ignoreLinks=False):
  '''
  Returns transformation matrices from local to global coordinate systems
  for given obj. More than one set of matrices may be returned if links
  exist in project.
  '''
  result = []
  for placement, path in allPlacementsAndPaths(obj, ignoreLinks=ignoreLinks):
    gpM = placement.toMatrix()
    gpMi = gpM.inverse()
    pM = obj.Placement.toMatrix()
    pMi = pM.inverse()
    result.append([gpM, gpMi, pM, pMi])
  return result


###################################################################################
# PRETTY PRINTING

def prettyPath(path):
  'insert labels into . separated object path for pretty printing'
  _path = []
  for p in path.split('.'):
    if p:
      pObj = simulation.simulatingDocument().getObject(p)
      _path.append(f'{pObj.Name}({pObj.Label})')
  return '.'.join(_path)

def matrixToArray(m):
  return array([
    [m.A11, m.A12, m.A13, m.A14],
    [m.A21, m.A22, m.A23, m.A24],
    [m.A31, m.A32, m.A33, m.A34],
    [m.A41, m.A42, m.A43, m.A44],
  ])

def matrixToString(m):
  return re.sub(r'\s+', '', repr(matrixToArray(m)))


###################################################################################
# SIMULATION LIFECYCLE HELPERS

class SimulationEnded(RuntimeError):
  pass

def keepGuiResponsive(raiseIfSimulationDone=False, minUpdateInterval=1/100):
  from ..detect_pyside import QApplication  
  global _LAST_PROCESS_EVENTS_CALL
  if time.time()-_LAST_PROCESS_EVENTS_CALL > minUpdateInterval:
    _LAST_PROCESS_EVENTS_CALL = time.time()

    if QApplication.instance():
      # process Qt events
      QApplication.processEvents()
      Gui.updateGui()

    # check whether simulation was canceled and raise SimulationEnded if so
    if raiseIfSimulationDone and (simulation.isCanceled() or simulation.isFinished()):
      raise SimulationEnded()
      
def keepGuiResponsiveAndRaiseIfSimulationDone():
  keepGuiResponsive(raiseIfSimulationDone=True)


###################################################################################
# PROTOTYPES FOR FREECAD ELEMENT PROXY CLASSES

class GenericFreecadElementProxy:
  def _properties(self):
    return []

  def _ensurePropertiesExist(self, obj):
    # create properties of object
    for section, entries in self._properties():
      for name, default, kind, tooltip in entries:
        if not hasattr(obj, name):
          obj.addProperty('App::Property'+kind, name, section, tooltip)
          setattr(obj, name, default)
    # trigger same operation for view object (if present)
    if ( hasattr(obj, 'ViewObject') 
         and hasattr(obj.ViewObject, 'Proxy')
         and hasattr(obj.ViewObject.Proxy, '_ensurePropertiesExist') ):
      obj.ViewObject.Proxy._ensurePropertiesExist(obj)


  @functools.wraps(allPlacementsAndPaths)
  def allPlacementsAndPaths(self, obj, **kwargs):
    return allPlacementsAndPaths(obj, **kwargs)


  @functools.cache
  def _getCoordinateTransformMatrices(self, obj, ignoreLinks=False):
    '''
    This is a prive method intended to be used by the ray-tracer only. Uses
    functools.cache to make sure matrices and vectors that do not change 
    during ray tracing are calculated only once.
    '''
    return allCoordinateTransformMatrices(obj, ignoreLinks=ignoreLinks)

  def _getCoordinateTransformMatricesWithoutLinks(self, obj):
    return self._getCoordinateTransformMatrices(obj, ignoreLinks=True)[0]


  def _onInitializeSimulation(self, obj, *args, **kwargs):
    '''
    Do not overload this method, use the version without underscore for overloading.
    This is akward but safer (using super()... in all inherited method is easily 
    overlooked which would result in very bad things)
    '''
    self._ensurePropertiesExist(obj)
    self._getCoordinateTransformMatrices.cache_clear()


  def _parsedDomain(self, domain, default=None, limits=None, spanLimits=None, isRecursive=False):
    '''
    Takes a string describing a domain for a variable and returns the (possibly corrected) string
    and the parsed result. 

    Arguments:
    domain:     string describing the domain, e.g. 9,inf
    default:    default string to use in case passed domain is invalid
    limits:     upper and lower limit for the allowed domain boundaries
    spanLimits: upper and lower limit for the allowed domain span
    '''
    # immediately set default if none is passed for domain
    if domain is None:
      domain = default
      if default is None:
        return '0,1', (0,1)

    # try to parse
    try:
      _domain = [float(sy.sympify(d).evalf()) for d in domain.split(',')]
    except Exception as e:
      if not isRecursive:
        io.err(f'invalid domain {domain}, {e.__class__.__name__}: {e}')
      return default, self._parsedDomain(default, None)[1]

    # make sure length is exactly two
    if _domain is not None and len(_domain) != 2:
      if not isRecursive:
        io.err(f'invalid domain {domain}, expect two numbers or inf separated by a ","')
      return default, self._parsedDomain(default, None)[1]

    # check if limits are in right order
    l1, l2 = _domain
    if l1 > l2:
      if not isRecursive:
        io.err(f'invalid domain {domain}, expect second value to be larger than first one.')
      flipped = ', '.join([s.strip() for s in reversed(domain.split(','))])
      return flipped, self._parsedDomain(flipped, None)[1]

    # check if limits are fulfilled
    if limits:
      _limits = [float(sy.sympify(l).evalf()) for l in limits]
      if l1 < _limits[0] or l2 > _limits[1]:
        if not isRecursive:
          io.err(f'domain {domain} out of bounds, expect both boundaries to be within {limits}.')
        orig1, orig2 = [s.strip() for s in domain.split(',')]
        limited = f'{limits[0] if l1 < _limits[0] else orig1}, {limits[1] if l2 > _limits[1] else orig2}'
        return limited, self._parsedDomain(limited, None)[1]

    # check if span limits are fulfilled
    if spanLimits and not isRecursive:
      _spanLimits = [float(sy.sympify(l).evalf()) for l in spanLimits]
      if l2-l1 < _spanLimits[0] or l2-l1 > _spanLimits[1]:
        # if this is a recursive call just return default to avoid possibility of endless recursion
        if isRecursive:
          return default, self._parsedDomain(default, None)[1]

        # if silence error is not set let's do our best to suggest a good domain
        else:
          io.err(f'domain span of {domain} out of bounds, expect {spanLimits[0]} <= domain span <= {spanLimits[1]} .')
          orig1, orig2 = [s.strip() for s in domain.split(',')]
          limited = f'{orig1}, {spanLimits[1] if l1==0 else {_spanLimits[1]}}'
          # silence errors and pass all limits etc. to recursive call here, because we might violate limits
          # with our enforced span limit
          return limited, self._parsedDomain(limited, default=default, limits=limits, 
                                             spanLimits=spanLimits, isRecursive=True)[1]

    # return original string and parsed domain
    return domain, _domain

  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''
    self._ensurePropertiesExist(obj)

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    self._ensurePropertiesExist(obj)

  def onInitializeSimulation(self, obj, *args, **kwargs):
    pass


class GenericFreecadElementViewProxy:
  def __init__(self, obj):
    pass

  def _properties(self):
    return []

  def _ensurePropertiesExist(self, obj):
    # create view object properties
    for section, entries in self._properties():
      for name, default, kind, tooltip in entries:
        if not hasattr(obj.ViewObject, name):
          obj.ViewObject.addProperty('App::Property'+kind, name, section, tooltip)
          setattr(obj.ViewObject, name, default)

  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''
    self._ensurePropertiesExist(obj)

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    self._ensurePropertiesExist(obj)


class GenericMakeFreecadElement:
  def __init__(self, proxyClass, viewProxyClass, 
               objectName, objectKind='App::LinkGroupPython'):
    self._proxyClass = proxyClass
    self._viewProxyClass = viewProxyClass
    self._objectName = objectName
    self._objectKind = objectKind

  def Activated(self):
    # create mirror object
    obj = App.activeDocument().addObject(self._objectKind, self._objectName)

    # register custom proxy and view provider proxy and ensure all properties exist
    obj.Proxy = self._proxyClass()
    obj.Proxy._ensurePropertiesExist(obj)
    if App.GuiUp:
      obj.ViewObject.Proxy = self._viewProxyClass(obj)
      obj.ViewObject.Proxy._ensurePropertiesExist(obj)

    # return created object
    return obj

  def IsActive(self):
    return True
