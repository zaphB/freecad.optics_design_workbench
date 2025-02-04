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
import sympy as sy

from .generic_source import *
from .common import *
from . import ray
from . import find
from .. import simulation
from .. import distributions
from .. import io

#####################################################################################################
class PointSourceProxy(GenericSourceProxy):

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''

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
  
    # reset random number generator mode to ? if power density expression is changed
    if prop in ('PowerDensity', 'PhiDomain', 'ThetaDomain', 
                'ThetaResolutionNumericMode', 'PhiResolutionNumericMode'):
      self._clearVrv(obj)


  def _getVrv(self, obj):
    if NON_SERIALIZABLE_STORE.get(self, None) is None:
      NON_SERIALIZABLE_STORE[self] = {}
    
    if NON_SERIALIZABLE_STORE[self].get('vrv', None) is None:
      # attach to obj and not to self, because attrbutes of self should be serializable
      NON_SERIALIZABLE_STORE[self]['vrv'] = (
            distributions.VectorRandomVariable(
                    obj.PowerDensity+'*abs(sin(theta))', # add correction for spherical coordinate area element size 
                    variableOrder=('theta', 'phi'),
                    variableDomains=dict(
                        theta=self.parsedThetaDomain(obj), 
                        phi=self.parsedPhiDomain(obj)),
                    numericalResolutions=dict(
                        theta=obj.ThetaResolutionNumericMode,
                        phi=obj.PhiResolutionNumericMode))
      )
      vrv = NON_SERIALIZABLE_STORE[self]['vrv']
      vrv.compile()
      obj.RandomNumberGeneratorMode = vrv.mode()
    return NON_SERIALIZABLE_STORE[self]['vrv']


  def _clearVrv(self, obj):
    _stored = NON_SERIALIZABLE_STORE.get(self, {})
    _stored['vrv'] = None
    NON_SERIALIZABLE_STORE[self] = _stored
    obj.RandomNumberGeneratorMode = '?'


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


  def makeRay(self, obj, theta, phi, power=1):
    '''
    Create new ray object with origin and direction given in global coordinates
    '''
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


  def _generateRays(self, obj, mode, maxFanCount=inf, maxRaysPerFan=inf, **kwargs):
    '''
    This generator yields each ray to be traced for one simulation iteration.
    '''
    rays = []

    # make sure GUI does not freeze
    keepGuiResponsiveAndRaiseIfSimulationDone()

    # determine number of rays to place
    raysPerIteration = 100
    if settings := find.activeSimulationSettings():
      raysPerIteration = settings.RaysPerIteration
    raysPerIteration *= obj.RaysPerIterationScale

    # fan-mode: generate fans of rays in spherical coordinates
    if mode == 'fans':
      raysPerIteration = min([obj.RaysPerFan, maxRaysPerFan])

      # create obj.Fans ray fans oriented in phi0
      for _phi in linspace(0, pi, int(min([obj.Fans, maxFanCount])+1))[:-1]:
        for phi in (_phi, _phi+pi):

          # this loop may run for quite some time, keep GUI responsive by handling events
          keepGuiResponsiveAndRaiseIfSimulationDone()

          # generate the required thetas to place beams at and create beams
          # create a scalar random variable here, treat Phi as a constant
          vrv = distributions.ScalarRandomVariable(
                      obj.PowerDensity, # no sin(theta) correction here because fans are 2D
                      variable='theta',
                      variableDomain=self.parsedThetaDomain(obj), 
                      numericalResolution=obj.ThetaResolutionNumericMode)
          vrv.compile(phi=phi)
          for theta in vrv.findGrid(N=raysPerIteration):

            # this loop may run for quite some time, keep GUI responsive by handling events
            keepGuiResponsiveAndRaiseIfSimulationDone()

            # add lines corresponding to this ray to total ray list
            yield self.makeRay(obj=obj, theta=theta, phi=phi)

    # true/pseudo random mode: place rays by drawing theta and phi from true random distribution
    elif mode == 'true' or mode == 'pseudo':

      # create/get random variable for theta and phi and draw samples 
      if mode == 'true':
        thetas, phis = self._getVrv(obj).draw(N=raysPerIteration)
      elif mode == 'pseudo':
        thetas, phis = self._getVrv(obj).drawPseudo(N=raysPerIteration)

      for theta, phi in zip(thetas, phis):

        # this loop may run for quite some time, keep GUI responsive by handling events
        keepGuiResponsiveAndRaiseIfSimulationDone()

        # create and trace ray
        yield self.makeRay(obj=obj, theta=theta, phi=phi)

    else:
      raise ValueError(f'unexpected ray placement mode {mode}')


#####################################################################################################
class PointSourceViewProxy(GenericSourceViewProxy):
  pass
  
#####################################################################################################
class AddPointSource(AddGenericSource):

  def Activated(self):
    # create new feature python object
    obj = App.activeDocument().addObject('App::LinkGroupPython', 'OpticalPointSource')

    # create properties of object
    for section, entries in [
      ('OpticalEmission', [
        ('PowerDensity', 'exp(-theta^2/0.01)', 'String',  
                  'Emitted optical power per solid angle. The expression may contain any mathematical '
                  'function contained in the numpy module, the polar angle "theta" and the azimuthal '
                  'angle "phi".'),
        ('Wavelength', 500, 'Float', 'Wavelength of the emitted light in nm.'),
        ('FocalLength', 0, 'Float', 'Distance of the ray origin from the location of the light source. '
                  'Negative values result in a converging beam.'),
        ('ThetaDomain', '0, pi/2', 'String', ''),
        ('PhiDomain', '0, 2*pi', 'String', ''),
      ]),
      ('OpticalSimulationSettings', [
        *self.defaultSimulationSettings(obj),
        ('RandomNumberGeneratorMode', '?', 'String', ''),
        ('ThetaResolutionNumericMode', 1000, 'Integer', ''),
        ('PhiResolutionNumericMode', 3, 'Integer', ''),
        ('Fans', 2, 'Integer', 'Number of ray fans to place in ray fan mode.'),
        ('RaysPerFan', 20, 'Integer', 'Number of rays to place per fan in ray fan mode.'),
       ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = PointSourceProxy()
    if App.GuiUp:
      obj.ViewObject.Proxy = PointSourceViewProxy()

    # make mode readonly
    obj.setEditorMode('RandomNumberGeneratorMode', 1)

    return obj

  def GetResources(self):
    return dict(Pixmap=self.iconpath(),
                Accel='',
                MenuText='Make point source',
                ToolTip='Add a point light source to the current project.')

def loadPointSource():
  Gui.addCommand('Add point source', AddPointSource())
