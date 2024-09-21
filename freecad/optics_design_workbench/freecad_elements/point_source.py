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
import numpy
import time
import functools
import sympy as sy

from . import ray
from . import find
from .common import *
from .. import simulation
from .. import distributions
from .. import io

#####################################################################################################
class PointSourceProxy():
  '''
  Proxy of the point point source object responsible for the logic
  '''
  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''
    # allow redrawing to allow previews during continuous simulation
    #simulation.cancelSimulation()

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    # dont cancel here because the constant redrawing triggers this
    #simulation.cancelSimulation()
    
    # make sure domains are valid
    if prop in ('PhiDomain', 'ThetaDomain'):
      raw = getattr(obj, prop)
      parsed, _ = self._parsedDomain(raw, {'PhiDomain': '0, 2*pi', 'ThetaDomain': '0, pi'}[prop])
      if raw != parsed:
        setattr(obj, prop, parsed)

    # make sure resolutions are valid
    if prop in ('ThetaResolutionNumericMode', 'PhiResolutionNumericMode'):
      if getattr(obj, prop) < 3:
        setattr(obj, prop, 3)
  
  def _parsedDomain(self, domain, default=None):
    # try to parse
    try:
      _domain = [float(sy.sympify(d).evalf()) for d in domain.split(',')]
    except Exception as e:
      io.err(f'invalid domain {domain}, {e.__class__.__name__}: {e}')
      return default, self._parsedDomain(default, None)[1]

    # make sure length is exactly two
    if _domain is not None and len(_domain) != 2:
      io.err(f'invalid domain {domain}, expect two numbers or inf separated by a ","')
      return default, self._parsedDomain(default, None)[1]

    # return original string and parsed domain
    return domain, _domain

  def parsedThetaDomain(self, obj):
    _, parsed = self._parsedDomain(obj.ThetaDomain)
    return parsed

  def parsedPhiDomain(self, obj):
    _, parsed = self._parsedDomain(obj.PhiDomain)
    return parsed

  def clear(self, obj):
    # remove shape but make sure placement stays alive
    placement = obj.Placement
    obj.Shape = Part.Shape()
    obj.Placement = placement
  
  def redraw(self, *args, **kwargs):
    self.runIteration(*args, draw=True, store=False, **kwargs)

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

  def makeRay(self, obj, theta, phi, power=1):
    gpM, gpMi, opticalAxis, orthoAxis, sourceOrigin = self._makeRayCache(obj)

    # apply azimuth and polar rotation to (0,0,1) vector
    ldirection = (Rotation(opticalAxis,phi/pi*180) 
                  * Rotation(orthoAxis,theta/pi*180) 
                  * opticalAxis)

    # shift origin to  all rays intersect in point (0,0,1)*focalLength
    lorigin = sourceOrigin + (opticalAxis-ldirection)*obj.FocalLength
    
    # apply global placement transformation to obtain global coordinates
    p1, p2 = lorigin, lorigin+ldirection/ldirection.Length
    p1, p2 = gpM*p1, gpM*p2
    gorigin, gdirection = p1, (p2-p1)/(p2-p1).Length
    return ray.Ray(obj, gorigin, gdirection, initPower=power)

  def runIteration(self, obj, mode, maxFanCount=inf, maxRaysPerFan=inf, draw=False, store=False, **kwargs):
    self._makeRayCache.cache_clear()
    rays = []

    # make sure GUI does not freeze
    processGuiEvents()

    # fan-mode: generate fans of rays in spherical coordinates
    if mode == 'fans':
      raysPerIteration = min([obj.RaysPerFan, maxRaysPerFan])

      # prepare expression
      densityExpr = sy.sympify(obj.PowerDensity)

      # create obj.Fans ray fans oriented in phi0
      for phi in linspace(0, pi, int(min([obj.Fans, maxFanCount])+1))[:-1]:

        # this loop may run for quite some time, keep GUI responsive by handling events
        processGuiEvents()

        # calculate desired beam power density
        densityLambda = sy.lambdify('theta', densityExpr.subs('phi', phi))
        thetas = linspace(*self.parsedThetaDomain(obj), obj.ThetaResolutionNumericMode)
        density = densityLambda(thetas)

        # generate the required thetas to place beams at and create beams
        for theta in distributions.generatePointsWithGivenDensity1D(
                                              density=(thetas, density),
                                              N=raysPerIteration,
                                              startFrom=0):

          # this loop may run for quite some time, keep GUI responsive by handling events
          processGuiEvents()

          # add lines corresponding to this ray to total ray list
          rays.append(self.makeRay(obj=obj, theta=theta, phi=phi))

    # pseudo-random mode: place rays by drawing theta and phi from pseudo random distribution
    elif mode == 'pseudo':
      # determine number of rays to place
      raysPerIteration = 100
      if settings := find.activeSimulationSettings():
        raysPerIteration = min([raysPerIteration, settings.RaysPerIteration])
      raysPerIteration *= obj.RaysPerIterationScale

      raise ValueError('not implemented')

    # true random mode: place rays by drawing theta and phi from true random distribution
    elif mode == 'true':

      # determine number of rays to place
      raysPerIteration = 100
      if settings := find.activeSimulationSettings():
        raysPerIteration = settings.RaysPerIteration
      raysPerIteration *= obj.RaysPerIterationScale

      # create random variable for theta and phi
      vrv = distributions.VectorRandomVariable(
                obj.PowerDensity, 
                variableOrder=('theta', 'phi'),
                variableDomains=dict(
                    theta=self.parsedThetaDomain(obj), 
                    phi=self.parsedPhiDomain(obj)),
                numericalResolutions=dict(
                    theta=obj.ThetaResolutionNumericMode,
                    phi=obj.PhiResolutionNumericMode))
      vrv.compile()

      thetas, phis = vrv.draw(raysPerIteration)
      for theta, phi in zip(thetas, phis):
        # this loop may run for quite some time, keep GUI responsive by handling events
        processGuiEvents()

        # create and trace ray
        rays.append(self.makeRay(obj=obj, theta=theta, phi=phi))

    else:
      raise ValueError(f'unexpected ray placement mode {mode}')

    # create compound containing all the lines and set it as the shape of the light source,
    # use inverse global transform because the Line freecad_elements are assigned as obj.Shape and
    # thus will be transformed by FreeCAD 
    gpM, gpMi = self._makeRayCache(obj)[:2]
    lines = []
    for r in rays:
      # add to ray to results storage
      if store:
        store.incrementRayCount()
        if obj.RecordRays:
          rayResults = store.addRay(source=obj)

      for (p1,p2), power, medium in r.traceRay(store=store, **kwargs):
        # this loop may run for quite some time, keep GUI responsive by handling events
        processGuiEvents()

        # add ray segment to storage if enabled
        if store and obj.RecordRays:
          # add segment to current ray in results storage
          rayResults.addSegment(points=(p1, p2), power=power, medium=medium)
        
        # add line to list of draw is enabled
        if draw:
          lines.append(Part.makeLine(gpMi*p1, gpMi*p2))
      
      # mark this ray is complete to permit flushing it
      if store and obj.RecordRays:
        rayResults.rayComplete()

    # set obj.Shape to display rays if draw is enabled
    if draw:
      if len(lines):
        placement = obj.Placement
        obj.Shape = Part.makeCompound(lines)
        obj.Placement = placement
      else:
        self.clear(obj)

#####################################################################################################
class PointSourceViewProxy():
  '''
  Proxy of the point point source object responsible for the view
  '''
  def getIcon(self):
    '''Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown.'''
    return find.iconpath('pointsource')

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
class AddPointSource():
  '''
  Command to add a new point source to the project
  '''
  def Activated(self):
    # create new feature python object
    obj = App.activeDocument().addObject('Part::FeaturePython', 'OpticalPointSource')

    # create properties of object
    for section, entries in [
      ('OpticalEmission', [
        ('PowerDensity', 'exp(-theta^2/0.01)', 'String',  
                  'Emitted optical power per solid angle. The expression may contain any mathematical '
                  'function contained in the numpy module, the polar angle "theta" and the azimuthal '
                  'angle "phi".'),
        ('Wavelength', 500, 'Float', 'Wavelength of the emitted light in nm.'),
        ('FocalLength', 0, 'Float', 'Distance of the ray origin from the location of the light source. '
                  'Negative values result in a converging beam.')
      ]),
      ('OpticalSimulationSettings', [
        ('RecordRays', False, 'Bool', ''),
        ('ThetaDomain', '-0.1, 0.1', 'String', ''),
        ('PhiDomain', '0, 2*pi', 'String', ''),
        ('ThetaResolutionNumericMode', 100, 'Integer', ''),
        ('PhiResolutionNumericMode', 100, 'Integer', ''),
        ('Fans', 2, 'Integer', 'Number of ray fans to place in ray fan mode.'),
        ('RaysPerFan', 20, 'Integer', 'Number of rays to place per fan in ray fan mode.'),
        ('IgnoredOpticalElements', [], 'LinkList', 'Rays of this source ignore the optical freecad_elements given'
                 ' in this list.'),
        ('RaysPerIterationScale', 1, 'Float', 'Number of rays to place per simulation iteration. '
                 'This will be multiplied with the RayCount property of the active simulation settings.'),
        ('MaxIntersectionsScale', 1, 'Float', 'Maximum number of intersections (reflections/refractions/'
                 'detections) that ray may have with optical objects. This will be '
                 'multiplied with the MaxIntersections property of the active simulation settings.'),
        ('MaxRayLengthScale', 1, 'Float', 'Maximum length of each ray segment. This will be '
                 'multiplied with the MaxRayLength property of the active simulation settings.'),
      ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # set default view properties
    obj.ViewObject.LineColor = (1.,.3,.0,.0)
    obj.ViewObject.Transparency = 30

    # register custom proxy and view provider proxy
    obj.Proxy = PointSourceProxy()
    obj.ViewObject.Proxy = PointSourceViewProxy()

    return obj

  def IsActive(self):
    return bool(App.activeDocument())

  def GetResources(self):
    return dict(Pixmap=find.iconpath('add-pointsource'),
                Accel='',
                MenuText='Make point source',
                ToolTip='Add a point light source to the current project.')

def loadPointSource():
  Gui.addCommand('Add point source', AddPointSource())
