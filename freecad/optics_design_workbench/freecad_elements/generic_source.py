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
from .. import io

# global dict with keys being PointSourceProxy objects and values being 
# more dicts that store pseudo-attributes. This akward attribute storing
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

  def clear(self, obj):
    # remove shape but make sure placement stays alive
    placement = obj.Placement
    obj.Shape = Part.Shape()
    obj.Placement = placement

  
  @functools.cache
  def _makeRayCache(self, obj):
    '''
    Make sure matrices and vectors that do not change during ray 
    tracing are calculated only once.
    '''
    gpM = obj.getGlobalPlacement().toMatrix()
    gpMi = obj.getGlobalPlacement().toMatrix().inverse()

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

    # prepare transforms etc that wil be used many times
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

      # trace ray through project
      for (p1,p2), power, medium in ray.traceRay(store=store, **kwargs):

        # this loop may run for quite some time, keep GUI responsive by handling events
        keepGuiResponsiveAndRaiseIfSimulationDone()

        # add segment to current ray in results storage if enabled
        if rayResults:
          rayResults.addSegment(points=(p1, p2), power=power, medium=medium)

        # draw line in GUI if desired
        if draw:
          # create new line element in local coordinates (global->local: transformed by inverse-GLOBAL-placement transform)
          newLineElement = Part.makeLine(gpMi*p1, gpMi*p2)

          # prepare list of existing shapes in local coordinates (with-placement-applied->local: transformed by inverse-placement transform)
          pMi = obj.Placement.toMatrix().inverse()
          existingShapes = [s.transformGeometry(pMi) for s in obj.Shape.SubShapes]

          # make new compound that contains the additional line and make sure Placement information
          # is restored properly, and clear transform matrix cache
          _placement = obj.Placement
          obj.Shape = Part.makeCompound(existingShapes + [newLineElement])
          obj.Placement = _placement
          self._makeRayCache.cache_clear()
        
      # increment ray count for progress tracking
      if store:
        store.incrementRayCount()

      # mark this ray is complete after tracing to permit flushing it if enabled
      if rayResults:
        rayResults.rayComplete()


#####################################################################################################
class GenericSourceViewProxy():
  '''
  Proxy of the point point source object responsible for the view
  '''
  def getIcon(self):
    '''Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown.'''
    return find.iconpath(self.__class__.__name__.replace('ViewProxy', '').lower())

  def attach(self, vobj):
    '''Setup the scene sub-graph of the view provider, this method is mandatory'''
    pass

  def updateData(self, obj, prop):
    '''If a property of the handled feature has changed we have the chance to handle this here'''
    pass

  def claimChildren(self):
    '''Return a list of objects that will be modified by this feature'''
    return []

  def onDelete(self, obj, subelements):
    '''Here we can do something when the feature will be deleted'''
    return True

  def onChanged(self, obj, prop):
    '''Here we can do something when a single property got changed'''
    pass


#####################################################################################################
class AddGenericSource():

  def iconpath(self):
    return find.iconpath('add-'+self.__class__.__name__.replace('Add', '').lower())

  def IsActive(self):
    return bool(App.activeDocument())

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

  def defaultViewSettings(self, obj):
    obj.ViewObject.LineColor = (1., .3, 0., 1.)
    obj.ViewObject.LineWidth = 1
