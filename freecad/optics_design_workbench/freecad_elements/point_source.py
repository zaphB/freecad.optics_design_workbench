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
import scipy.optimize
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
    if prop in ('PhiDomain', 'ThetaDomain', 'RadiusDomain'):
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
      elif prop == 'RadiusDomain':
        default = '0,10'
        limits = [0,inf]
        spanLimits = [0,inf]

      # parse range and replace value in case parsing changed it
      parsed, (l1,l2) = self._parsedDomain(raw, default=default, 
                                           limits=limits, 
                                           spanLimits=spanLimits)
      if raw != parsed:
        setattr(obj, prop, parsed)
      
      # inter-update theta and radius domains if possible, avoid recursion by only
      # updating the hidden one of the two domains when the non-hidden one changes
      if isfinite(float(obj.FocalLength)):
        if prop == 'ThetaDomain':
          if l1 < pi/2-1e-5 and l2 < pi/2-1e-5 and not isclose(float(obj.FocalLength), 0):
            r1, r2 = abs(tan(l1)*float(obj.FocalLength)), abs(tan(l2)*float(obj.FocalLength))
            r2 = max([0.1, r1+0.1, r2])
            setattr(obj, 'RadiusDomain', ', '.join(['0' if r==0 
                                                      else f'{r:.1e}' if abs(r)<0.01 or abs(r)>300
                                                      else f'{r:.2f}' if abs(r) < 3
                                                      else f'{r:.1f}' if abs(r) < 30
                                                      else f'{r:.0f}'
                                                          for r in sorted([r1,r2])]))
      else:
        if prop == 'RadiusDomain':
          if _lastFiniteF:=getattr(self, '_lastFiniteFocalLength', nan):
            t1, t2 = sorted([ arctan(l1/abs(_lastFiniteF)), arctan(l2/abs(_lastFiniteF)) ])
            t2 = max([0.01*pi, t1+0.01*pi, t2])
            if hasattr(obj, 'ThetaDomain'): # <- this is needed during startup to avoid 'attribute not found error'
              setattr(obj, 'ThetaDomain', ', '.join(['0' if t==0 else f'{t/pi:.2f}*pi'
                                                                    for t in [t1,t2] ]))

    # make sure resolutions are valid
    if prop in ('ThetaResolutionNumericMode', 'RadiusResolutionNumericMode', 
                'PhiResolutionNumericMode'):
      try:
        float(getattr(obj, prop))
      except Exception:
        io.err(f'tried to set {prop} to {getattr(obj, prop)}, which is not a valid number')
        if prop.startswith('Theta'):
          setattr(obj, prop, '1e6')
        else:
          setattr(obj, prop, '4')
      if float(getattr(obj, prop)) < 3:
        setattr(obj, prop, '3')
  
    # reset random number generator mode to ? if power density expression is changed
    if prop in ('PowerDensity', 'PhiDomain', 
                'ThetaDomain', 'RadiusDomain', 
                'ThetaResolutionNumericMode', 
                'RadiusResolutionNumericMode'
                'PhiResolutionNumericMode'):
      self._clearVrv(obj)

    # sync theta and radius resolution
    if prop in ('ThetaResolutionNumericMode',
                'RadiusResolutionNumericMode'):
      val = getattr(obj, prop)
      for k in ('ThetaResolutionNumericMode',
                'RadiusResolutionNumericMode'):
        # hasattr here is needed to avoid 'attribute not found' error during startup
        if k!=prop and hasattr(obj, k) and getattr(obj, k, None) != val:
          setattr(obj, prop, val)

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

    # parse focal length
    if prop == 'FocalLength':
      val = getattr(obj, prop)
      try:
        val = float(val)
      except ValueError:
        setattr(obj, prop, '0')
      else:
        # show theta or radius range depending on whether focal length is finite or not
        if isfinite(float(val)):
          if float(val) != 0:
            self._lastFiniteFocalLength = float(val)
          obj.setEditorMode('ThetaDomain', 0)
          obj.setEditorMode('RadiusDomain', 3)
          obj.setEditorMode('ThetaResolutionNumericMode', 0)
          obj.setEditorMode('RadiusResolutionNumericMode', 3)
        else:
          obj.setEditorMode('ThetaDomain', 3)
          obj.setEditorMode('RadiusDomain', 0)
          obj.setEditorMode('ThetaResolutionNumericMode', 3)
          obj.setEditorMode('RadiusResolutionNumericMode', 0)

    # update divergence if focal length, emission density expression or other 
    # dependent property changed
    if prop in ('FocalLength', 'PowerDensity', 'ThetaDomain', 'ThetaResolutionNumericMode'):
      f = getattr(obj, 'FocalLength', None)
      expr = getattr(obj, 'PowerDensity', None)
      prevDivergence = getattr(obj, 'Divergence', None)
      if f is not None and expr is not None:
        f = float(f)
        if not isfinite(f):
          setattr(obj, 'Divergence', '0')
        else:
          # set divergence to read only if variables other than r exist
          # in expression
          if [str(s) for s in sy.sympify(expr).free_symbols] == ['r']:
            obj.setEditorMode('Divergence', 0)
          else:
            obj.setEditorMode('Divergence', 1)

          # create theta-only expression and find divergence angle
          expr = sy.sympify(expr).subs('r', sy.sympify(f'(tan(theta)*{f})'))
          syms = [str(s) for s in expr.free_symbols]
          if syms == ['theta'] and self.parsedThetaDomain(obj)[0] == 0:
            maxPower = sy.lambdify('theta', expr)(0)
            try:
              divergenceAngle = scipy.optimize.bisect(sy.lambdify('theta', expr - maxPower/e), 
                                                      0, self.parsedThetaDomain(obj)[1])
            except Exception:
              io.warn(f'failed to find 1/e angle in emission power expression {expr} within theta '
                      f'domain {self.parsedThetaDomain(obj)}, does the power emission decrease for '
                      f'theta>0? is the theta domain large enough?')
              setattr(obj, 'Divergence', '-')
            else:
              if (prevDivergence is None 
                    or prevDivergence == '-' 
                    or not isclose(float(eval(prevDivergence)), divergenceAngle) ):
                setattr(obj, 'Divergence', f'{-sign(f)*divergenceAngle/pi:.6g}*pi')
          else:
            setattr(obj, 'Divergence', '-')

    # update focal length if divergence changed (this can only be done if 
    # power emission is parametrized by radius only)
    if prop == 'Divergence':
      divergence = getattr(obj, 'Divergence', None)
      if divergence is not None and divergence != '-':
        newDivergenceAngle = float(eval(divergence))

      # try to find 1/e radius of power density
      f = getattr(obj, 'FocalLength', None)
      expr = getattr(obj, 'PowerDensity', None)
      if f is not None and expr is not None:
        f = float(f)
        expr = sy.sympify(expr)
        syms = [str(s) for s in expr.free_symbols]
        if syms == ['r'] and self.parsedRadiusDomain(obj)[0] == 0:
          maxPower = sy.lambdify('r', expr)(0)
          try:
            oneOverERadius = scipy.optimize.bisect(sy.lambdify('r', expr - maxPower/e), 
                                                   0, self.parsedRadiusDomain(obj)[1])
          except Exception:
            io.warn(f'failed to find 1/e angle in emission power expression {expr} within theta '
                    f'domain {self.parsedThetaDomain(obj)}, does the power emission decrease for '
                    f'theta>0? is the theta domain large enough?')
            setattr(obj, 'Divergence', '-')
          else:
            if isclose(newDivergenceAngle, 0):
              setattr(obj, 'FocalLength', 'inf')
            else:
              newFocalLength = -oneOverERadius/tan(newDivergenceAngle)
              if not isclose(newFocalLength, f, rtol=1e-5):
                setattr(obj, 'FocalLength', f'{newFocalLength:.6g}')
        else:
          setattr(obj, 'FocalLength', getattr(obj, 'FocalLength'))


  def _rvArgs(self, obj, densityString, variableDomain=None):
    useTheta = isfinite(float(obj.FocalLength))
    useRadius = not isfinite(float(obj.FocalLength))
    usePhi = variableDomain is None
    if useTheta:
      # raise error if focal length is zero and r,x or y exist in density expression (except for
      # characters in function names)
      if isclose(float(obj.FocalLength), 0):
        for c in 'rxy':
          if c in ( densityString.replace('exp', '').replace('arcsin', '').replace('arccos', '')
                                .replace('arctan', '').replace('arctan2', '').replace('arccot', '')
                                .replace('arsinh', '').replace('arcosh', '').replace('artanh', '')
                                .replace('arcoth', '') ):
            raise ValueError(f'Variable {c} in power density expression {obj.PowerDensity} '
                             f'is forbidden if focal length is zero.')

      # substitute r,x,y by theta,phi expressions
      f = f'{abs(float(obj.FocalLength)):.8e}'
      densityString = (sy.sympify(densityString)
                          .subs('r', sy.sympify(f'(tan(theta)*{f})'))
                          .subs('x', sy.sympify(f'(tan(theta)*cos(phi)*{f})'))
                          .subs('y', sy.sympify(f'(tan(theta)*sin(phi)*{f})')))
      if usePhi:
        return dict(
            probabilityDensity=densityString,
            variableOrder=('theta', 'phi'),
            variableDomains=dict(
                theta=self.parsedThetaDomain(obj), 
                phi=self.parsedPhiDomain(obj)),
            numericalResolutions=dict(
                theta=float(obj.ThetaResolutionNumericMode),
                phi=float(obj.PhiResolutionNumericMode))
        )
      else:
        return dict(
            probabilityDensity=densityString,
            variable='theta',
            variableDomain=variableDomain,
            numericalResolution=float(obj.ThetaResolutionNumericMode),
        )
    if useRadius:
      # replace sin(theta) with radius
      densityString = densityString.replace('sin(theta)', 'r')

      # raise error if theta exists in density expression
      if 'theta' in densityString:
        raise ValueError(f'Variable theta in power density expression {obj.PowerDensity} '
                         f'is forbidden if focal length is infinite.')

      # substitute theta,x,y and by r,phi expressions
      densityString = (sy.sympify(densityString)
                              .subs('x', sy.sympify(f'(r*cos(phi))'))
                              .subs('y', sy.sympify(f'(r*sin(phi))')))
      if usePhi:
        return dict(
            probabilityDensity=densityString,
            variableOrder=('r', 'phi'),
            variableDomains=dict(
                r=self.parsedRadiusDomain(obj), 
                phi=self.parsedPhiDomain(obj)),
            numericalResolutions=dict(
                r=float(obj.RadiusResolutionNumericMode),
                phi=float(obj.PhiResolutionNumericMode))
        )
      else:
        return dict(
            probabilityDensity=densityString,
            variable='r',
            variableDomain=variableDomain,
            numericalResolution=float(obj.RadiusResolutionNumericMode),
        )

  def _parsedFanPhi0(self, obj):
    return float(sy.sympify(getattr(obj, 'FanPhi0')).evalf())

  def _getVrv(self, obj):
    if NON_SERIALIZABLE_STORE.get(self, None) is None:
      NON_SERIALIZABLE_STORE[self] = {}
    
    if NON_SERIALIZABLE_STORE[self].get('vrv', None) is None:
      # attach to obj and not to self, because attributes of self should be serializable
      NON_SERIALIZABLE_STORE[self]['vrv'] = (
            distributions.VectorRandomVariable(
                **self._rvArgs(obj,
                    obj.PowerDensity+'*abs(sin(theta))', # add correction for spherical coordinate area element size 
                )
            )
      )
      vrv = NON_SERIALIZABLE_STORE[self]['vrv']
      vrv.compile()
      obj.RandomNumberGeneratorMode = vrv.mode()
    return NON_SERIALIZABLE_STORE[self]['vrv']


  def _clearVrv(self, obj):
    _stored = NON_SERIALIZABLE_STORE.get(self, {})
    _stored['vrv'] = None
    NON_SERIALIZABLE_STORE[self] = _stored
    # hasattr line is needed to avoid 'attribute not found' error during startup
    if hasattr(obj, 'RandomNumberGeneratorMode'):
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
          return limited, self._parsedDomain(limited, default=default, limits=limits, 
                                             spanLimits=spanLimits, isRecursive=True)[1]

    # return original string and parsed domain
    return domain, _domain

  def parsedThetaDomain(self, obj):
    _, parsed = self._parsedDomain(obj.ThetaDomain)
    return parsed

  def parsedRadiusDomain(self, obj):
    _, parsed = self._parsedDomain(obj.RadiusDomain)
    return parsed

  def parsedPhiDomain(self, obj):
    _, parsed = self._parsedDomain(obj.PhiDomain)
    return parsed


  def makeRay(self, obj, theta, phi, power=1, metadata={}):
    '''
    Create new ray object with origin and direction given in global coordinates
    '''
    gpM, gpMi, opticalAxis, orthoAxis, sourceOrigin = self._makeRayCache(obj)

    # normal point source with finite focal length
    if isfinite(float(obj.FocalLength)):
      # apply azimuth and polar rotation to (0,0,1) vector
      ldirection = (Rotation(opticalAxis,phi/pi*180) 
                    * Rotation(orthoAxis,theta/pi*180) 
                    * opticalAxis)

      # shift origin to  all rays intersect in point (0,0,1)*focalLength
      lorigin = sourceOrigin + (opticalAxis-ldirection)*float(obj.FocalLength)

      # calc initial radius
      radius = tan(theta)*float(obj.FocalLength)

    # infinite focal length: passed theta is actually radius
    else:
      ldirection = opticalAxis
      lorigin = (sourceOrigin 
                  + App.Vector(theta*orthoAxis*cos(phi))
                  + App.Vector(theta*cross(orthoAxis, opticalAxis)*sin(phi)))
      radius = theta
      theta = nan
    
    # apply global placement transformation to obtain global coordinates
    p1, p2 = lorigin, lorigin+ldirection/ldirection.Length
    p1, p2 = gpM*p1, gpM*p2
    gorigin, gdirection = p1, (p2-p1)/(p2-p1).Length

    # build metadata dict
    rayMetadata = dict(initPhi=phi, initTheta=theta, initRadius=radius)
    rayMetadata.update(metadata)

    # return actual ray object
    return ray.Ray(obj, gorigin, gdirection, wavelength=obj.Wavelength, 
                   initPower=power, metadata=rayMetadata)


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

      # reset flag to report fan mode once
      self._reportedFullFanMode = None

      # create obj.Fans ray fans oriented in phi0
      totalFanCount = int(min([obj.Fans, maxFanCount]))
      for fanIndex, _phi in enumerate(self._parsedFanPhi0(obj) + linspace(0, pi, totalFanCount+1)[:-1]):

        # generate the required thetas to place beams, calc the phi+pi part of the
        # fan using using positive and negative thetas here
        if isfinite(float(obj.FocalLength)):
          l1, l2 = self.parsedThetaDomain(obj)
        else:
          l1, l2 = self.parsedRadiusDomain(obj)
        if l1 == 0:
          isFullFanMode = True
          _report = getattr(self, '_reportedFullFanMode', None)
          if _report is None or _report != isFullFanMode:
            io.verb(f'using full fan-mode')
            self._reportedFullFanMode = True
          srv = distributions.ScalarRandomVariable(
                  **self._rvArgs(obj,
                      # no sin(theta) correction here because fans are 2D, but make sure theta 
                      # is taken as absolute value because of the negative-theta-hack:
                      str(sy.sympify(obj.PowerDensity).subs('theta', 'abs(theta)').subs('r', 'abs(r)')),
                      variableDomain=(-l2,l2)
                  )
          )
          # TODO: compile twice, once with _phi, once with _phi+pi, then add method to fetch the
          #       numerical densities from both compiles, merge both densities, 
          #       find grid of combined
          srv.compile(phi=_phi)
          _posNegThetas = srv.findGrid(N=raysPerFan)
          #io.verb(f'{_posNegThetas=}, {-l2=}, {l2=}')

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
            srv = distributions.ScalarRandomVariable(
                    **self._rvArgs(obj,
                        # no sin(theta) correction here because fans are 2D
                        obj.PowerDensity,
                        variableDomain=(l1,l2)
                    )
            )
            srv.compile(phi=_phi)
            _thetas = srv.findGrid(N=raysPerFan)
            totalRaysInFan = 2*len(_thetas)
            #io.verb(f'{_thetas=}')

          # this loop may run for quite some time, keep GUI responsive by handling events
          keepGuiResponsiveAndRaiseIfSimulationDone()

          for rayIndex, theta in enumerate(sorted(_thetas)):

            # if number of rays is even: dont use index=zero, start with +1 and
            # -1 on each side of the fan, respectively
            if raysPerFan % 2 == 0:
              rayIndex += 1

            # if number of rays is odd: place index=zero on the central theta
            else:
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
                  'function contained in the numpy module, the polar angle "theta" the azimuthal '
                  'angle "phi", the radial distance "r" and the cartesian coordinates "x" and "y". '
                  '"theta" and "phi" refer to a spherical coordinate system centered in the focal '
                  'point of the light source. '
                  '"r", "x" and "y" refer to a coordinate system in the emission plane (=plane '
                  'orthogonal to optical axis) centered at the intersection of emission plane and '
                  'optical axis. '
                  'All rays placed by this light source begin in the emission plane.'),
        ('Wavelength', 500, 'Float', 'Wavelength of the emitted light in nm.'),
        ('FocalLength', '0', 'String', 'Distance from the ray origin at which all rays (would) intersect. '
                  'Positive values result in converging, negative values result in a diverging '
                  'beam. For a parallel light source use "inf".'),
        ('Divergence', '-', 'String', 'Angle at which a rays at 1/e emission power diverge from the '
                  'optical axis. This option is writable only if the only unknown in the Power Density '
                  'expression is "r" (no theta, phi, x, y), if Power Density drops below 1/e for a '
                  'finite r and if Focal Length is finite. Changing divergence will update Focal Length '
                  'and vice versa. The option is readable if "theta" exists in the Power Density '
                  'expression.'),
        ('ThetaDomain', '0, pi/4', 'String', 'Min and max value for polar angle theta to consider.'),
        ('RadiusDomain', '0, 10', 'String', 'Min and max value for azimuthal angle phi to consider.'),
        ('PhiDomain', '0, 2*pi', 'String', 'Min and max value for radial distance r to consider.'),
      ]),
      ('OpticalSimulationSettings', [
        *self.defaultSimulationSettings(obj),
        ('RandomNumberGeneratorMode', '?', 'String', ''),
        ('ThetaResolutionNumericMode', '1e6', 'String', ''),
        ('RadiusResolutionNumericMode', '1e6', 'String', ''),
        ('PhiResolutionNumericMode', '3', 'String', ''),
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
