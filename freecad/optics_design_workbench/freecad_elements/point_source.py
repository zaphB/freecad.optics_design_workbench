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

from . import ray
from . import find
from .. import simulation
from .. import distributions
from .. import io

from .generic_source import *
from .common import *
from ..simulation.raytracing_cache import *

#####################################################################################################
class PointSourceProxy(GenericSourceProxy):

  def _properties(self):
    return [
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
        ('PhiDomain', '0, 2*pi', 'String', 'Min and max value for azimuthal angle phi to consider.'),
        ('RadiusDomain', '0, 10', 'String', 'Min and max value for radial distance r to consider.'),
      ]),
      ('OpticalSimulationSettings', [
        ('RandomNumberGeneratorMode', '?', 'String', ''),
        ('ThetaResolutionNumericMode', '1e5', 'String', ''),
        ('RadiusResolutionNumericMode', '1e5', 'String', ''),
        ('PhiResolutionNumericMode', '1e2', 'String', ''),
        ('Fans', 2, 'Integer', 'Number of ray fans to place in ray fan mode.'),
        ('FanPhi0', '0', 'String', 'Change this to rotate fans around optical axis.'),
        ('RaysPerFan', 20, 'Integer', 'Number of rays to place per fan in ray fan mode.'),
      ]),
    ]+super()._properties()


  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    self._ensurePropertiesExist(obj)

    # make sure domains are valid
    if prop in ('PhiDomain', 'ThetaDomain', 'RadiusDomain'):
      raw = getattr(obj, prop)

      # select defaults and limits depending on property
      if prop == 'PhiDomain':
        default = '0,2*pi'
        limits = ['-20*pi', '20*pi']
        spanLimits = [0, '20*pi']
      elif prop == 'ThetaDomain':
        default = '0,pi/4'
        limits = ['-20*pi','20*pi']
        spanLimits = [0, '20*pi']
      elif prop == 'RadiusDomain':
        default = '0,10'
        limits = [-inf,inf]
        spanLimits = [0,inf]

      # parse range and replace value in case parsing changed it
      parsed, (l1,l2) = self._parsedDomain(raw, default=default, 
                                           limits=limits, 
                                           spanLimits=spanLimits)
      if raw != parsed:
        setattr(obj, prop, parsed)
      
      # inter-update theta and radius domains if possible, avoid recursion by only
      # updating the hidden one of the two domains when the non-hidden one changes
      # (check for hasattr Focal length because e.g. surface source inherits this
      #  onChanged handler but removes the focal length property)
      if hasattr(obj, 'FocalLength') and isfinite(float(getattr(obj, 'FocalLength', 1))):
        if prop == 'ThetaDomain':
          if l1 < pi/2-1e-5 and l2 < pi/2-1e-5 and not isclose(float(obj.FocalLength), 0):
            r1, r2 = abs(tan(l1)*float(obj.FocalLength)), abs(tan(l2)*float(obj.FocalLength))
            r2 = max([0.1, r1+0.1, r2])
            if isfinite(r1) and isfinite(r2):
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
            if isfinite(t1) and isfinite(t2):
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

    # check for hasattr focal length and divergence because e.g. surface source inherits this
    # onChanged handler but removes the focal length property
    if ( hasattr(obj, 'FocalLength') and hasattr(obj, 'Divergence') ):

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
            if not isclose(f, 0) and syms == ['theta'] and self.parsedThetaDomain(obj)[0] == 0:
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


  def _rvArgs(self, obj, densityString, variableDomain=None, scalarRandomVar=False):
    'make kwargs dictionary to initialize a scalar or vector random variable from the power density string'

    # if focal length has a finite value means we want to generate rays in spherical coordinates
    # using theta and phi angles.
    if isfinite(float(getattr(obj, 'FocalLength', 1))):

      # raise error if focal length is zero and r,x or y exist in density expression (except for
      # characters in function names)
      if isclose(float(getattr(obj, 'FocalLength', 1)), 0):
        for c in 'rxy':
          if c in ( _s:=densityString.replace('exp', '').replace('arcsin', '').replace('arccos', '')
                                 .replace('arctan', '').replace('arctan2', '').replace('arccot', '')
                                 .replace('arsinh', '').replace('arcosh', '').replace('artanh', '')
                                 .replace('arcoth', '').replace('DiracDelta', '').replace('Piecewise', '')
                                 .replace('Heaviside', '').replace('True', '').replace('False', '') ):
            raise ValueError(f'Variable {c} in power density expression {obj.PowerDensity} '
                             f'is forbidden if focal length is zero . ({_s=})')

      # if we are making a 2D random variable (not 1D scalar random variable) we have to account
      # for area element size in spherical coordinates:
      if not scalarRandomVar:
        densityString = '('+densityString+')*abs(sin(theta))'

      # substitute r,x,y by theta,phi expressions
      f = f'{abs(float(getattr(obj, "FocalLength", 1))):.8e}'
      densityExpr = (sy.sympify(densityString)
                            .subs('r', sy.sympify(f'(tan(theta)*{f})'))
                            .subs('x', sy.sympify(f'(tan(theta)*cos(phi)*{f})'))
                            .subs('y', sy.sympify(f'(tan(theta)*sin(phi)*{f})')))

      # if scalar random variable is requested: treat phi as a constant that has to
      # be passed to compile (used in fan mode)
      if scalarRandomVar:
        return dict(
            probabilityDensity=str(densityExpr),
            variable='theta',
            variableDomain=variableDomain,
            numericalResolution=float(obj.ThetaResolutionNumericMode),
        )
      # else: return args to create vector random variable using theta and phi
      return dict(
        probabilityDensity=str(densityExpr),
        variableOrder=('theta', 'phi'),
        variableDomains=dict(
            theta=self.parsedThetaDomain(obj), 
            phi=self.parsedPhiDomain(obj)),
        numericalResolutions=dict(
            theta=float(obj.ThetaResolutionNumericMode),
            phi=float(obj.PhiResolutionNumericMode))
      )

    # ..if however focal length is infinite (parallel ray source), the angle theta has no meaning and we have to 
    # generate rays in cylinder coordinates using r and phi.
    else:
      # if we are making a 2D random variable (not 1D scalar random variable) we have to account
      # for area element size in cylinder coordinates:
      if not scalarRandomVar:
        densityString = '('+densityString+')*abs(r)'

      # raise error if theta exists in density expression
      if 'theta' in densityString:
        raise ValueError(f'Variable theta in power density expression {obj.PowerDensity} '
                         f'is forbidden if focal length is infinite.')

      # substitute theta,x,y and by r,phi expressions
      densityExpr = (sy.sympify(densityString)
                            .subs('x', sy.sympify(f'(r*cos(phi))'))
                            .subs('y', sy.sympify(f'(r*sin(phi))')))
      
      # if scalar random variable is requested: treat phi as a constant that has to
      # be passed to compile (used in fan mode)
      if scalarRandomVar:
        return dict(
            probabilityDensity=str(densityExpr),
            variable='r',
            variableDomain=variableDomain,
            numericalResolution=float(obj.RadiusResolutionNumericMode),
        )
      # else: return args to create vector random variable using theta and phi
      return dict(
          probabilityDensity=str(densityExpr),
          variableOrder=('r', 'phi'),
          variableDomains=dict(
              r=self.parsedRadiusDomain(obj), 
              phi=self.parsedPhiDomain(obj)),
          numericalResolutions=dict(
              r=float(obj.RadiusResolutionNumericMode),
              phi=float(obj.PhiResolutionNumericMode))
      )

  def _parsedFanPhi0(self, obj):
    return float(sy.sympify(getattr(obj, 'FanPhi0')).evalf())

  def _getVrv(self, obj, **kwargs):
    if NON_SERIALIZABLE_STORE.get(self, None) is None:
      NON_SERIALIZABLE_STORE[self] = {}
    
    if NON_SERIALIZABLE_STORE[self].get('vrv', None) is None:
      # module global variable and not to self, because attributes of self should be serializable
      NON_SERIALIZABLE_STORE[self]['vrv'] = (
            (distributions.ScalarRandomVariable 
                if kwargs.get('scalarRandomVar', False) 
                else distributions.VectorRandomVariable )(
                      **self._rvArgs(obj, obj.PowerDensity, **kwargs) )
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


  def parsedThetaDomain(self, obj):
    _, parsed = self._parsedDomain(obj.ThetaDomain)
    return parsed

  def parsedRadiusDomain(self, obj):
    _, parsed = self._parsedDomain(obj.RadiusDomain)
    return parsed

  def parsedPhiDomain(self, obj):
    _, parsed = self._parsedDomain(obj.PhiDomain)
    return parsed


  def _makeRay(self, obj, thetaOrRadius, phi, power=1, metadata={}):
    '''
    Create new ray object with origin and direction given in global coordinates,
    if focal length is infinite, theta parameter is treated as radius.
    '''
    gpM, gpMi, pM, pMi = self._getCoordinateTransformMatricesWithoutLinks(obj)

    # setup a few standard vectors in local coordinates
    opticalAxis = Vector(0,0,1)
    orthoAxis = Vector(1,0,0)
    sourceOrigin = Vector(0,0,0)

    # normal point source with finite focal length
    if isfinite(float(obj.FocalLength)):
      # with finite focal length both theta and radius are defined
      theta = thetaOrRadius
      radius = tan(theta)*float(obj.FocalLength)

      # apply azimuth and polar rotation to (0,0,1) vector
      ldirection = (Rotation(opticalAxis,phi/pi*180) 
                    * Rotation(orthoAxis,theta/pi*180) 
                    * opticalAxis)

      # shift origin to  all rays intersect in point (0,0,1)*focalLength
      lorigin = sourceOrigin + (opticalAxis-ldirection)*float(obj.FocalLength)

    # infinite focal length: passed theta is actually radius
    else:
      # with infinite focal length only radius is well defined
      radius = thetaOrRadius
      theta = nan

      ldirection = opticalAxis
      lorigin = (sourceOrigin 
                  + App.Vector(radius*orthoAxis*cos(phi))
                  + App.Vector(radius*cross(orthoAxis, opticalAxis)*sin(phi)))
    
    # apply global placement transformation to obtain global coordinates
    p1, p2 = lorigin, lorigin+ldirection/ldirection.Length
    p1, p2 = gpM*p1, gpM*p2
    gorigin, gdirection = p1, (p2-p1)/(p2-p1).Length

    # build metadata dict
    rayMetadata = dict(initPhi=phi, initTheta=theta, initRadius=radius)
    rayMetadata.update(metadata)

    # return actual ray object
    return ray.Ray(obj, gorigin, gdirection, wavelength=
                   cachedProperty(obj, 'Wavelength'), 
                   initPower=power, metadata=rayMetadata)


  def _generateRays(self, obj, mode, maxFanCount=inf, maxRaysPerFan=inf, **kwargs):
    '''
    This generator yields each ray to be traced for one simulation iteration.
    '''
    # make sure GUI does not freeze
    keepGuiResponsiveAndRaiseIfSimulationDone()

    # ensure that all required properties exist for this object 
    self._ensurePropertiesExist(obj)

    # fan-mode: generate fans of rays in spherical coordinates
    if mode == 'fans':
      
      # fetch parameters for fan calculation
      raysPerFan = min([obj.RaysPerFan, maxRaysPerFan])
      totalFanCount = int(min([obj.Fans, maxFanCount]))

      # determine domain limits of theta or radius var
      if isfinite(float(obj.FocalLength)):
        l1, l2 = self.parsedThetaDomain(obj)
      else:
        l1, l2 = self.parsedRadiusDomain(obj)

      # determine limits of phi
      phiL1, phiL2 = self.parsedPhiDomain(obj)

      # Per definition one fan covers both phi and phi+pi sides of the optical axis. Depending on the domain
      # for theta (or radius) three different cases apply:
      # 1) l1>0, gapped-fan mode: rays for two fan sides have to be calculated independently 
      #          (this requires even number of rays)
      # 2) l1==0, stitched-fan mode: two fan sides are calculated using positive theta (radius only), but on
      #          one side phi is replaced with phi+pi (possibly +2pi*n, to make sure other side of fan is part
      #          of phi-domain)
      # 3) l1<0, theta-sign-change fan mode: two fan sides are calculated using positive and negative 
      #          theta (radius)
      #
      # (above l1 conditions apply for positive l1 and l2, actual conditions for all signs follow)
      if l1>0 and l2>0 or l1<0 and l2<0:
        fanMode = 'gapped'
        raysPerFan = max([ 4, int(ceil(raysPerFan/2)*2) ]) # (ensure even number of rays, at least 4)
      elif l1==0 or l2==0:
        fanMode = 'stitched'
      elif l1 < 0 and l2 > 0:
        fanMode = 'theta-sign-change'
      else:
        raise ValueError(f'{l1=}, {l2=}')
      io.verb(f'using fan generation mode "{fanMode}"')

      # create obj.Fans ray fans, with first fan oriented as phi0
      for fanIndex, _phi in enumerate(self._parsedFanPhi0(obj) + linspace(0, pi, totalFanCount+1)[:-1]):
        keepGuiResponsiveAndRaiseIfSimulationDone()

        # find angles phiA and phiB that both lie in phiDomain if possible, phiA is as close to _phi as
        # possible, phiB is the opposite side of the fan (or nan if this side is not part of phiDomain)
        _phiCandidates = [ phi for phi in arange(_phi-30*pi, _phi+31*pi, pi) 
                                                    if phiL1-1e-9 <= phi and phi <= phiL2+1e-9 ]
        if not len(_phiCandidates):
          io.verb(f'skipping {fanIndex=} because no suitable angle phi is in phi domain')
          continue
        phiA = _phiCandidates[argmin(abs(_phi-_phiCandidates))]
        # generate second list of candidates for opposite fan side, this time only look at phiA plus/minus
        # odd multiples of 2*pi, because adding even multiples of pi would be equivalent to phiA. 
        _phiCandidates = [ phi for phi in arange(phiA+pi -30*pi, phiA+pi +31*pi, 2*pi) 
                                                    if phiL1-1e-9 <= phi and phi <= phiL2+1e-9 ]
        if not len(_phiCandidates):
          phiB = nan
        else:
          phiB = _phiCandidates[argmin(abs(phiA+pi - _phiCandidates))]
        print(f'{phiA=}, {phiB=}, {phiL1=}, {phiL2=}')

        # generate the required thetas (radii) to place rays depending on the fanMode (see long
        # comment above for fanModes)
        if fanMode == 'gapped':
          srv = distributions.ScalarRandomVariable(
            **self._rvArgs(obj,
                # no sin(theta) correction here because fans are 2D
                obj.PowerDensity,
                variableDomain = (l1,l2),
                scalarRandomVar = True,
            )
          )
          srv.compile(phi=phiA)
          valuesFanSide1 = srv.findGrid(N=raysPerFan//2)
          srv.compile(phi=phiB)
          valuesFanSide2 = srv.findGrid(N=raysPerFan//2)

        # stitched fan mode (see long comment above for details on fanModes)
        elif fanMode == 'stitched':
          limit = max([abs(l1), abs(l2)])
          var = 'theta' if isfinite(float(obj.FocalLength)) else 'r'
          srv = distributions.ScalarRandomVariable(
            **self._rvArgs(obj,
                # no sin(theta) correction here because fans are 2D, but replace:
                #  theta and radius with their absolute values, because we are 
                #                         setting their limits to -limit,limit
                #  phi with piecewise phiA and phiB depending on sign of 
                #             theta/radius to switch to other side of optical 
                #             axis on theta handle sign change
                #  if however phiB is None (=this side of the fan does not fall
                #             within phiDomain, record power density from 0 to
                #             var lim only)
                ((
                  str(sy.sympify(obj.PowerDensity)
                          .subs('theta', 'abs(theta)')
                          .subs('r', 'abs(r)')
                          .subs('phi', f'Piecewise( ( ({phiA}), ({var})>0 ), '
                                                  f'( ({phiB}),  True     ) )'))
                )
                if isfinite(phiB) else 
                (
                  str(sy.sympify(obj.PowerDensity)
                          .subs('theta', 'abs(theta)')
                          .subs('r', 'abs(r)'))
                )),
                variableDomain = (-limit,limit) if isfinite(phiB) else (0, limit),
                scalarRandomVar = True,
            )
          )
          srv.compile(phi=phiA)
          valuesFanSide1 = srv.findGrid(N=raysPerFan)
          valuesFanSide2 = []

        # stitched fan mode (see long comment above for details on fanModes)
        elif fanMode == 'theta-sign-change':
          srv = distributions.ScalarRandomVariable(
            **self._rvArgs(obj,
                # no sin(theta) correction here because fans are 2D
                obj.PowerDensity,
                variableDomain = (l1,l2),
                scalarRandomVar = True,
            )
          )
          srv.compile(phi=phiA)
          valuesFanSide1 = srv.findGrid(N=raysPerFan)
          valuesFanSide2 = []

        else:
          raise ValueError(f'{fanMode=}')

        # if two fan sides were generated, no index=zero, start indexing with 
        # +1 and -1 on each respective side, ensure values in each fan side are
        # sorted by absolute value to start from the center
        if len(valuesFanSide2) > 0:
          valuesFanSide1 = sorted(valuesFanSide1, key=abs)
          valuesFanSide2 = sorted(valuesFanSide2, key=abs)
          indicesFanSide1 = list(1+arange(len(valuesFanSide1)))
          indicesFanSide2 = list(-(1+arange(len(valuesFanSide2))))

        # if just one side exists: sort numerically (not absolute value) and
        # ray closest do optical axis gets index=zero couting up/down to both
        # sides from there
        else:
          valuesFanSide1 = sorted(valuesFanSide1)
          _i0 = argmin(abs(valuesFanSide1))
          indicesFanSide1 = list(arange(len(valuesFanSide1))-_i0)
          indicesFanSide2 = []

        # pack both fan sides values, indices and phiA/B into one list, iterate
        # through them by starting from smallest indices by absolute value 
        # (add -.1 for the sorting key to always start with positive sign index)
        packedIVPhi = [(i,v,phi) 
                          for i,v,phi in list(zip(indicesFanSide1, valuesFanSide1, 
                                                  [phiA]*len(valuesFanSide1)))
                                        +list(zip(indicesFanSide2, valuesFanSide2, 
                                                  [phiB]*len(valuesFanSide2)))]
        for rayIndex, thetaOrRadius, phi in sorted(packedIVPhi, key=lambda e: abs(e[0])-.1):
          keepGuiResponsiveAndRaiseIfSimulationDone()

          # add lines corresponding to this ray to total ray list
          yield self._makeRay(obj=obj, 
                              thetaOrRadius=thetaOrRadius, 
                              phi=phi,
                              metadata=dict(fanIndex=int(fanIndex), 
                                            rayIndex=int(rayIndex),
                                            totalFanCount=int(totalFanCount),
                                            totalRaysInFan=len(packedIVPhi)))

    # true/pseudo random mode: place rays by drawing theta and phi from true random distribution
    elif mode == 'true' or mode == 'pseudo':

      # determine number of rays to place
      raysPerIteration = 100
      if settings := find.activeSimulationSettings():
        raysPerIteration = settings.RaysPerIteration
      raysPerIteration *= obj.RaysPerIterationScale

      # create/get random variable for theta and phi and draw samples 
      if mode == 'true':
        thetasOrRadii, phis = self._getVrv(obj).draw(N=raysPerIteration)
      elif mode == 'pseudo':
        thetasOrRadii, phis = self._getVrv(obj).drawPseudo(N=raysPerIteration)

      for thetaOrRadius, phi in zip(thetasOrRadii, phis):

        # this loop may run for quite some time, keep GUI responsive by handling events
        keepGuiResponsiveAndRaiseIfSimulationDone()

        # create and trace ray
        yield self._makeRay(obj=obj, thetaOrRadius=thetaOrRadius, phi=phi)

    else:
      raise ValueError(f'unexpected ray placement mode {mode}')


#####################################################################################################
class PointSourceViewProxy(GenericSourceViewProxy):
  pass
  
#####################################################################################################
class AddPointSource(AddGenericSource):

  def __init__(self):
    super().__init__(PointSourceProxy, PointSourceViewProxy, 'OpticalPointSource')

  def Activated(self):
    obj = super().Activated()

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
