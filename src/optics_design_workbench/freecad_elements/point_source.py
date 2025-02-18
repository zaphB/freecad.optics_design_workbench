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

      # select defaults and limits depending on property
      if prop == 'PhiDomain':
        default = '0,2*pi'
        limits = ['-2*pi', '2*pi']
        spanLimits = [0, '2*pi']
      elif prop == 'ThetaDomain':
        default = '0,pi'
        limits = ['0','pi']
        spanLimits = [0, 'pi']

      # parse range and replace value in case parsing changed it
      parsed, _ = self._parsedDomain(raw, default=default, 
                                     limits=limits, 
                                     spanLimits=spanLimits)
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

    # parse fanPhi0
    if prop == 'FanPhi0':
      try:
        parsed = self._parsedFanPhi0(obj) 
      except Exception:
        io.err(f'invalid value for FanPhi0')
        setattr(obj, prop, '0')
      else:
        if parsed < -2*pi:
          io.err(f'value for FanPhi0 out of range [-2*pi, 2*pi]')
          setattr(obj, prop, '-2*pi')
        if parsed > 2*pi:
          io.err(f'value for FanPhi0 out of range [-2*pi, 2*pi]')
          setattr(obj, prop, '2*pi')

  def _parsedFanPhi0(self, obj):
    return float(sy.sympify(getattr(obj, 'FanPhi0')).evalf())

  def _getVrv(self, obj):
    if NON_SERIALIZABLE_STORE.get(self, None) is None:
      NON_SERIALIZABLE_STORE[self] = {}
    
    if NON_SERIALIZABLE_STORE[self].get('vrv', None) is None:
      # attach to obj and not to self, because attributes of self should be serializable
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


  def _parsedDomain(self, domain, default=None, limits=None, spanLimits=None, isRecursive=False):
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
          return limited, self._parsedDomain(limited, defailt=default, limits=limits, 
                                             spanLimits=spanLimits, isRecursive=True)[1]

    # return original string and parsed domain
    return domain, _domain

  def parsedThetaDomain(self, obj):
    _, parsed = self._parsedDomain(obj.ThetaDomain)
    return parsed

  def parsedPhiDomain(self, obj):
    _, parsed = self._parsedDomain(obj.PhiDomain)
    return parsed


  def makeRay(self, obj, theta, phi, power=1, metadata={}):
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

    # build metadata dict
    rayMetadata = dict(initPhi=phi, initTheta=theta)
    rayMetadata.update(metadata)

    # return actual ray object
    return ray.Ray(obj, gorigin, gdirection, initPower=power, metadata=rayMetadata)


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
      raysPerFan = min([obj.RaysPerFan, maxRaysPerFan])

      # create obj.Fans ray fans oriented in phi0
      totalFanCount = int(min([obj.Fans, maxFanCount]))
      for fanIndex, _phi in enumerate(self._parsedFanPhi0(obj) + linspace(0, pi, totalFanCount+1)[:-1]):

        # generate the required thetas to place beams, calc the phi+pi part of the
        # fan using using positive and negative thetas here
        l1, l2 = self.parsedThetaDomain(obj)
        if l1 == 0:
          isFullFanMode = True
          _report = getattr(self, '_reportedFullFanMode', None)
          if _report is None or _report != isFullFanMode:
            io.verb(f'using full fan-mode')
            self._reportedFullFanMode = True
          vrv = distributions.ScalarRandomVariable(
                      # no sin(theta) correction here because fans are 2D, but make sure theta 
                      # is taken as absolute value because of the negative-theta-hack:
                      obj.PowerDensity.replace('theta', 'abs(theta)'),
                      variable='theta',
                      variableDomain=(-l2,l2), 
                      numericalResolution=obj.ThetaResolutionNumericMode)
          vrv.compile(phi=_phi)
          _posNegThetas = vrv.findGrid(N=raysPerFan)
          #io.verb(f'{_posNegThetas=}')

          # store whether most central ray has positive of negative theta to
          # decide later where to place rayIndex==0
          _isCentralThetaNegative = (abs(_posNegThetas).min() < 0)

        # make one iteration per ray fan half
        for rayIndexSign, phi in ([1, _phi], [-1, _phi+pi]):

          # select thetas belonging to this half of the fan
          if l1 == 0:
            if rayIndexSign == 1:
              _thetas = _posNegThetas[_posNegThetas>=0]
            else:
              _thetas = -_posNegThetas[_posNegThetas<0]
            totalRaysInFan = len(_posNegThetas)

          # generate the required thetas to place beams in two halves if 
          # lower theta limit l1 is not zero
          else:
            isFullFanMode = False
            _report = getattr(self, '_reportedFullFanMode', None)
            if _report is None or _report != isFullFanMode:
              io.verb(f'using split fan-mode')
              self._reportedFullFanMode = False
            vrv = distributions.ScalarRandomVariable(
                        # no sin(theta) correction here because fans are 2D
                        obj.PowerDensity,
                        variable='theta',
                        variableDomain=(l1,l2), 
                        numericalResolution=obj.ThetaResolutionNumericMode)
            vrv.compile(phi=_phi)
            _thetas = vrv.findGrid(N=raysPerFan)
            totalRaysInFan = 2*len(_thetas)
            #io.verb(f'{_thetas=}')

          # this loop may run for quite some time, keep GUI responsive by handling events
          keepGuiResponsiveAndRaiseIfSimulationDone()

          for rayIndex, theta in enumerate(sorted(_thetas)):

            if isFullFanMode:
              # increment index if we are on the side of the fan that is 
              # to avoid having two rayIndex==0 rays 
              if (       (_isCentralThetaNegative and rayIndexSign == +1)
                  or (not _isCentralThetaNegative and rayIndexSign == -1) ):
                rayIndex += 1
            else:
              # in split ray fan mode just increment the negative ray indices
              # by one to avoid having rayIndex==0 twice
              if rayIndexSign == -1:
                rayIndex += 1

            # this loop may run for quite some time, keep GUI responsive by handling events
            keepGuiResponsiveAndRaiseIfSimulationDone()

            # add lines corresponding to this ray to total ray list
            yield self.makeRay(obj=obj, theta=theta, phi=phi, 
                               metadata=dict(fanIndex=fanIndex, 
                                             rayIndex=rayIndex*rayIndexSign,
                                             totalFanCount=totalFanCount,
                                             totalRaysInFan=totalRaysInFan))

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
        ('FanPhi0', '0', 'String', 'Change this to rotate fans around optical axis.'),
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
