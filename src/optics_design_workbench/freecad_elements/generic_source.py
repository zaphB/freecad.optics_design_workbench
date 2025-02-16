__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

try:
  import FreeCADGui as Gui
  import FreeCAD as App
  from FreeCAD import Vector, Rotation
  import Part
except ImportError:
  pass

from numpy import *
import functools

from .common import *
from . import find
from .. import simulation
from ..simulation.tracing_cache import *
from .. import io

# global dict with keys being PointSourceProxy objects and values being 
# more dicts that store pseudo-attributes. This awkward attribute storing
# format allows to bypass the serializer which wants to safe the Proxy
# objects whenever the FreeCAD project is saved.
NON_SERIALIZABLE_STORE = {}


#####################################################################################################
class GenericSourceProxy():
  '''
  Proxy of the point point source object responsible for the logic
  '''
  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    print(obj, prop)

  def clear(self, obj):
    # delete all children, which are the RaySegments
    if hasattr(obj, 'ElementList'):
      for segment in obj.ElementList:
        simulation.simulatingDocument().removeObject(segment.Name)
    else:
      raise RuntimeError(f'light source object {obj.Name} does not have ElementList property. Older project? Recreate the source.')

  @functools.cache
  def _makeRayCache(self, obj):
    '''
    Make sure matrices and vectors that do not change during ray 
    tracing are calculated only once.
    '''
    # TODO: LinkGroupPython has no global placement method... Is this sufficient?
    gpM = obj.Placement.toMatrix()
    gpMi = obj.Placement.toMatrix().inverse()
    #elem = obj.ElementList[0]
    #gpM = obj.Shape.getGlobalPlacement().toMatrix()
    #gpMi = obj.Shape.getGlobalPlacement().toMatrix().inverse()
    
    # prepare Placement-adjusted beam orientation vectors in local coordinates
    opticalAxis = Vector(0,0,1)
    orthoAxis = Vector(1,0,0)
    sourceOrigin = Vector(0,0,0)

    return gpM, gpMi, opticalAxis, orthoAxis, sourceOrigin

  def onInitializeSimulation(self, obj, state, ident):
    pass

  def onExitSimulation(self, obj, ident):
    pass

  def runSimulationIteration(self, obj, *, mode, draw=False, store=False, **kwargs):
    # recalculate cached matrices for each iteration
    self._makeRayCache.cache_clear()

    # prepare transforms etc that will be used many times
    gpM, gpMi = self._makeRayCache(obj)[:2]

    # clear displayed rays on begin of each simulation iteration
    self.clear(obj)

    # generate rays that we want to trace in this iteration
    for ray in self._generateRays(obj, mode=mode, **kwargs):

      # add to ray object to results storage if desired
      rayResults = None
      if store and obj.RecordRays:
        if obj.RecordRays:
          rayResults = store.addRay(source=obj)

      # reference to previously drawn ray object updated in ray tracing loop, initialize
      # with ray of color given by light source
      prevRaySegment = None

      # set starting color to diffuse color of light source at begin of tracing
      # the diffuse color is the first one visible in the view settings, so it
      # is most intuitive to use this
      if _vobj:=cachedViewObject(obj):
        color = _vobj.ShapeMaterial.DiffuseColor

      # trace ray through project
      for (p1,p2), power, medium, colorChange in ray.traceRay(store=store, **kwargs):

        # this loop may run for quite some time, keep GUI responsive by handling events
        keepGuiResponsiveAndRaiseIfSimulationDone()

        # add segment to current ray in results storage if enabled
        if rayResults:
          rayResults.addSegment(points=(p1, p2), power=power, medium=medium)

        # draw line in GUI if desired
        if draw:
          # create new line element in local coordinates (global->local: transformed by inverse-GLOBAL-placement transform)
          newLineElement = Part.makeLine(gpMi*p1, gpMi*p2)

          # if color change is requested or no ray segment Part::Feature exists yet, 
          # add new Part::Feature with updated color
          if colorChange is not None or prevRaySegment is None:
            
            # calculate new color if needed
            if colorChange is not None:
              weight, newColor = colorChange
              weight = min([1, max([0, weight])])
              color = tuple(array(color)*(1-weight) + array(newColor)*weight)
          
            # create new line element and add to ray source group, set visibility to false at 
            # first to avoid rays being shown with wrong placement for a very short moment
            _obj = simulation.simulatingDocument().addObject('Part::Feature', f'RaySegment')
            _obj.Visibility = False
            if cachedViewObject(_obj):
              _obj.ViewObject.ShowInTree = False
              _obj.ViewObject.LineWidth = cachedViewObject(obj).LineWidth
              _obj.ViewObject.LineColor = color

            # make sure to create a compound with one member, instead of setting the line directly as Shape
            # setting a line directly makes the SubShapes correspond to its Vertices, which will break
            # adding possible adding of line segments to the compound in following iterations (else branch of this)
            _obj.Shape = Part.makeCompound([newLineElement])
            obj.ElementList = obj.ElementList + [_obj]
            prevRaySegment = _obj

          # if now color change is requested, add line segment as compound
          else:
            prevRaySegment.Shape = Part.makeCompound(prevRaySegment.Shape.SubShapes + [newLineElement])
        
      # increment ray count for progress tracking
      if store:
        store.incrementRayCount()

      # mark this ray is complete after tracing to permit flushing it if enabled
      if rayResults:
        rayResults.rayComplete()


#####################################################################################################
class GenericSourceViewProxy():

  def getIcon(self):
    '''Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown.'''
    return find.iconpath(self.__class__.__name__.replace('ViewProxy', '').lower())

  def attach(self, vobj):
    NON_SERIALIZABLE_STORE[self] = vobj.Object

  def updateData(self, obj, prop):
    '''If a property of the handled feature has changed we have the chance to handle this here'''
    pass

  def claimChildren(self):
    '''Return a list of objects that will be modified by this feature'''
    return NON_SERIALIZABLE_STORE[self].ElementList

  def onDelete(self, vobj, subelements):
    # make sure all ray segments are deleted
    NON_SERIALIZABLE_STORE[self].Proxy.clear(NON_SERIALIZABLE_STORE[self])
    return True

  def onChanged(self, obj, prop):
    '''Here we can do something when a single property got changed'''
    pass


#####################################################################################################
class AddGenericSource():

  def iconpath(self):
    return find.iconpath('add-'+self.__class__.__name__.replace('Add', '').lower())

  def IsActive(self):
    return True

  def defaultSimulationSettings(self, obj):
    return [
      ('RecordRays', False, 'Bool', ''),
      ('IgnoredOpticalElements', [], 'LinkList', 'Rays of this source ignore the optical freecad_elements given'
                ' in this list.'),
      ('RaysPerIterationScale', 1, 'Float', 'Number of rays to place per simulation iteration. '
                'This will be multiplied with the RayCount property of the active simulation settings.'),
      ('MaxIntersectionsScale', 1, 'Float', 'Maximum number of intersections (reflections/refractions/'
                'detections) that ray may have with optical objects. This will be '
                'multiplied with the MaxIntersections property of the active simulation settings.'),
      ('MaxRayLengthScale', 1, 'Float', 'Maximum length of each ray segment. This will be '
                'multiplied with the MaxRayLength property of the active simulation settings.'),
    ]
