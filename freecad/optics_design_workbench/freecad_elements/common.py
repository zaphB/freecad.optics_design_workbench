__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

import time
import sympy as sy

from .. import io
from .. import simulation
from .. import distributions

_LAST_PROCESS_EVENTS_CALL = time.time()
_MIN_UPDATE_INTERVAL = 1e-2

# global dict with keys being proxy objects and values being 
# more dicts that store pseudo-attributes. This awkward attribute storing
# format allows to bypass the serializer which wants to save the Proxy
# objects whenever the FreeCAD project is saved.
NON_SERIALIZABLE_STORE = {}


class SimulationEnded(RuntimeError):
  pass

def keepGuiResponsive(raiseIfSimulationDone=False):
  from ..detect_pyside import QApplication  
  global _LAST_PROCESS_EVENTS_CALL
  if time.time()-_LAST_PROCESS_EVENTS_CALL > _MIN_UPDATE_INTERVAL:
    _LAST_PROCESS_EVENTS_CALL = time.time()

    if QApplication.instance():
      # process Qt events
      QApplication.processEvents()
      Gui.updateGui()
      QApplication.processEvents()

    # check whether simulation was canceled and raise SimulationEnded if so
    if raiseIfSimulationDone and (simulation.isCanceled() or simulation.isFinished()):
      raise SimulationEnded()
      
def keepGuiResponsiveAndRaiseIfSimulationDone():
  keepGuiResponsive(raiseIfSimulationDone=True)


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
