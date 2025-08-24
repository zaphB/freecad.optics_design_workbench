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
import functools

from .generic_source import *
from .point_source import PointSourceProxy
from .common import *
from . import ray
from . import find
from .. import simulation
from .. import distributions
from .. import io

#####################################################################################################
class SurfaceSourceProxy(PointSourceProxy):

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    # first call onChanged of point source
    super().onChanged(obj, prop)

    # parse UV map sampling settings
    if prop in ('UVSamplingInitialResolution', 'UVSamplingMaxRelAreaElementChange'):
      default = {'UVSamplingInitialResolution': '5', 'UVSamplingMaxRelAreaElementChange': '0.1'}[prop]
      raw = getattr(obj, prop)
      try:
        parsed = float(raw)
      except Exception:
        setattr(obj, prop, default)


  def onInitializeSimulation(self, obj, state, ident):
    # reset cached face uv maps on every simulation start
    io.verb('clearing self._sampleAreaElementsOnFace cache')
    self._sampleAreaElementsOnFace.cache_clear()
    self._cachedSelectedFace.cache_clear()


  def parsedPhiDomain(self, obj):
    return (0, 2*pi)


  def _makeRay(self, obj, origin, faceTangent, faceNormal, 
               theta, phi, power=1, metadata={}):
    '''
    Create new ray object with origin and direction given in global coordinates
    '''
    # apply azimuth and polar rotation to faceNormal vector
    direction = (Rotation(faceNormal,phi/pi*180) 
                  * Rotation(faceTangent,theta/pi*180) 
                  * faceNormal)

    # build metadata dict
    rayMetadata = dict(initPhi=phi, initTheta=theta)
    rayMetadata.update(metadata)

    # return actual ray object
    return ray.Ray(obj, origin, direction, wavelength=obj.Wavelength, 
                   initPower=power, metadata=rayMetadata)


  def _getDistTol(self, distTol=None):
    if distTol is None:
      distTol = 1e-2
      if settings := find.activeSimulationSettings():
        distTol = float(settings.DistanceTolerance)
    return max([distTol, 1e-6])


  def _makeSurfaceGrid(self, obj, face, totalGridPoints,
                       uniformParam=None, fillFactor=1, 
                       effectiveSizes=None, recursionDepth=0):
    '''
    Prepare a list of (u,v) points that have approximately equal distance on a given
    face, most parameters will be found out and refined in a number of recursive calls
    '''
    # calculate distance tolerance
    distTolerance = self._getDistTol()

    # setup limits and sizes dicts (if not given)
    _r = face.ParameterRange
    limits = dict(u=(_r[0], _r[1]), v=(_r[2], _r[3]))
    paramSizes = dict(u=_r[1]-_r[0], v=_r[3]-_r[2])
    if effectiveSizes is None:
      effectiveSizes = paramSizes

    # decide which param to put first, param with longer span in front by default, 
    # but if uniform param is known put uniform param first
    paramOrder = 'uv' if effectiveSizes['u']>=effectiveSizes['v'] else 'vu'
    if uniformParam is not None:
      paramOrder = uniformParam+{'u':'v', 'v':'u'}[uniformParam]

    # generate very simple rectilinear grid with minimum 5x5 points, p1 and p2 correspond to u and v as given by
    # value of paramOrder
    P1, P2 = [ linspace(limits[p][0], limits[p][1], 
                        max([5, 1+int( 2*round( sqrt(effectiveSizes[p]/effectiveSizes[_p] * totalGridPoints/fillFactor)/2 )) ]) )
                                                                                    for p, _p in zip(paramOrder, reversed(paramOrder)) ]
    p1Step = P1[1]-P1[0]
    p2Step = P2[1]-P2[0]

    # convenience functions to map p1 and p2 to u and v
    uv = lambda p1, p2: (p1,p2) if paramOrder=='uv' else (p2,p1)
    p1p2 = lambda u, v: (u,v) if paramOrder=='uv' else (v,u)

    # calculate locations of all mesh points and find out whether they are actually part of the mesh
    points = [[ face.valueAt(*uv(p1,p2)) for p2 in P2 ] for p1 in P1 ]
    isValid = [[ Part.Vertex(p).distToShape(face)[0] < distTolerance for p in row] for row in points ]

    # calculate derivatives at all valid locations, place (None,None) placeholders outside of face
    derivatives = [[ p1p2(*face.derivative1At(*uv(p1,p2))) if isValid[i][j] else (None,None) 
                                                                    for j,p2 in enumerate(P2) ]
                                                                          for i,p1 in enumerate(P1) ]
    derivP1 = [[ d[0].Length if d[0] is not None else None for d in row ] for row in derivatives ]
    derivP2 = [[ d[1].Length if d[1] is not None else None for d in row ] for row in derivatives ]
    areaElems = [[ dp1*dp2 if dp1 is not None and dp2 is not None else None
                             for dp1, dp2 in zip(dP1, dP2) ] for dP1, dP2 in zip(derivP1, derivP2) ]

    # check whether p1 (or p2) looks uniform, if yes -> update value of uniformParam
    _mean = lambda A: (lambda _A: mean(_A) if len(_A) else None)([a for a in A if a is not None])
    _max = lambda A: (lambda _A: max(_A) if len(_A) else None)([a for a in A if a is not None])
    _sum = lambda A: sum([a for a in A if a is not None])
    _dAvgs = [ _mean(row) for row in areaElems ]
    isUniformP1 = all([all([ abs(d-dAvg)*p1Step*p2Step < distTolerance**2 for d in row if d is not None ])
                                                                 for dAvg, row in zip(_dAvgs, areaElems) ])
    #print(f'{paramOrder=}, {isUniformP1=}')
    if isUniformP1:
      uniformParam = paramOrder[0]
    else:
      _dAvgs = [ _mean(row) for row in zip(*areaElems) ]
      isUniformP2 = all([all([ abs(d-dAvg)*p1Step*p2Step < distTolerance**2 for d in row if d is not None ]) 
                                                                for dAvg, row in zip(_dAvgs, zip(*areaElems)) ])
      #print(f'{paramOrder=}, {isUniformP2=}')
      if isUniformP2:
        uniformParam = paramOrder[1]
      # neither of the two looks uniform? reset uniform paramValue to None
      else:
        uniformParam = None

    # recalculate effective sizes of p1 and p2 axes using averaged derivatives
    effTotalLengthP1 = _sum([ _max(row) for row in derivP1 ])*p1Step
    effTotalLengthP2 = _sum([ _max(row) for row in zip(*derivP2) ])*p2Step
    effectiveSizes = {paramOrder[0]: effTotalLengthP1, paramOrder[1]: effTotalLengthP2}

    # if first param is uniform, check whether p1Step times derivative in p1 direction matches 
    # design value, thin down if not the case
    #print(f'{paramOrder}, {paramSizes}')
    if uniformParam is not None:
      for i,row in enumerate(derivP2):
        effectiveRowLen = max([1e-20, p2Step*_sum([dp2 for dp2 in row if dp2 is not None])])
        keepEveryNthEntry = 2**round(log2(effTotalLengthP2/effectiveRowLen))
        #print(f'{i}, {effectiveRowLen=}, {effTotalLengthP2=}, {effectiveRowLen/effTotalLengthP2=} {keepEveryNthEntry=}')
        # if keepEveryNth is greater than count, keep only first one
        if keepEveryNthEntry > len(isValid[i]):
          for j in range(1, len(isValid[i])):
            isValid[i][j] = False

        # set isValid to false for entries that we do not want to keep
        else:
          for j in range(len(isValid[i])):
            if j%keepEveryNthEntry != 0:
              isValid[i][j] = False

    # calculate updated value for fillfactor
    validCount = sum([sum([1 if v else 0 for v in row]) for row in isValid ])
    updatedFillFactor = validCount / (len(P1)*len(P2))
    #print(f'{len(P1)=} {len(P2)=} {fillFactor=}, {updatedFillFactor=} {validCount=}')

    # recurse three times to refine fillFactor, effectiveSizes and uniformParam values 
    if recursionDepth < 3:
      return self._makeSurfaceGrid(obj, face, totalGridPoints, 
                                   uniformParam=uniformParam,
                                   # avoid fillFactor jumping to zero if none if the initial rays is on the face
                                   fillFactor=max([fillFactor/10, updatedFillFactor]),
                                   effectiveSizes=effectiveSizes,
                                   recursionDepth=recursionDepth+1)

    # remove outer points if requested very few points and too many were created
    dropEveryCandidates = [lambda i,j: False, lambda i,j: i%2==0 or j%2==0, lambda i,j: ((i+1)//2)%2==0 or ((j+1)//2)%2==0]
    validCount = sum([sum([1 if v else 0 for v in row]) for row in isValid ])
    while len(dropEveryCandidates) and totalGridPoints < 20 and validCount > totalGridPoints:
      drop = dropEveryCandidates.pop(0)
      isValid = [[ (isValid[i][j] 
                    and not drop(i,j))
                             for j,p in enumerate(row) ] for i,row in enumerate(points) ]
      validCount = sum([sum([1 if v else 0 for v in row]) for row in isValid ])

    # return all validated u,v pairs, also return points and derivatives for potential reuse
    return [(uv(p1,p2), points[i][j], uv(*derivatives[i][j]))
                            for i,p1 in enumerate(P1)
                                  for j,p2 in enumerate(P2) if isValid[i][j]]

  @functools.cache
  def _sampleAreaElementsOnFace(self, obj, face):
    io.verb(f'generating grid of finite area element sizes on {self}, {obj=}, {obj.Name=}, {face}, ')
    # calculate distance tolerance
    distTolerance = self._getDistTol()

    # get u and v limits and spans
    uMin, uMax, vMin, vMax = face.ParameterRange
    uSpan, vSpan = uMax-uMin, vMax-vMin

    # define little subroutine with caching to speed up
    @functools.cache
    def _calcP(u, v):
      return face.valueAt(u, v)

    @functools.cache
    def _isOnFace(p):
      return Part.Vertex(p).distToShape(face)[0] < distTolerance

    @functools.cache
    def _calcDeriv(u, v):
      return face.derivative1At(u,v)

    # calculate points and area elements of the initial grid
    def calcPdA(U, V):
      P = []
      dA = []
      valid = []
      for u in U:
        dA.append([])
        P.append([])
        valid.append([])
        for v in V:
          # this loop may run for quite some time, keep GUI responsive by handling events
          keepGuiResponsiveAndRaiseIfSimulationDone()

          # calc points and derivatives and construct result array
          p = _calcP(u, v)
          P[-1].append(p)
          valid[-1].append(_isOnFace(tuple(p)))
          du, dv = _calcDeriv(u, v)

          # IMPORTANT: do not get the idea to set area elements outside of shape to NaN or similar,
          #            this will degrade the random number generator resolution close to the face
          #            boundaries! Therefore we have to calculate area elements for the entire UV-space,
          #            even the UV points that are not on the face, i.e. valid[i,j]==False
          dA[-1].append(du.cross(dv).Length)
      dA, P = array(dA), array(P)
      return P, dA, valid

    # create simple rectilinear grid to begin with, increase sampling density until at least 9 valid points are found
    resolution = max([ 3, int(round(float(obj.UVSamplingInitialResolution))) ])
    while True:
      # this loop may run for quite some time, keep GUI responsive by handling events
      keepGuiResponsiveAndRaiseIfSimulationDone()

      U, V = linspace(uMin, uMax, resolution), linspace(vMin, vMax, resolution)
      P, dA, valid = calcPdA(U, V)
      validCount = sum(valid)
      if validCount >= 9:
        break
      resolution *= 2
      if resolution > 1e2:
        raise ValueError(f'failed to sample UV mesh on face {face}, because no valid u,v value pair could be determined')

    # find row/col with largest curvature (but still lying within face) -> insert new cols/rows to enhance resolution
    maxAreaElementDiff = float(obj.UVSamplingMaxRelAreaElementChange)
    while True:
      # update P and dA arrays
      P, dA, valid = calcPdA(U, V)

      # calc relative difference of neighboring area elements
      _meanA = mean(dA[isfinite(dA)])
      areaDiffs1 = abs(( (dA[1:,:]-dA[:-1,:]) / _meanA )).max(axis=1)
      areaDiffs2 = abs(( (dA[:,1:]-dA[:,:-1]) / _meanA )).max(axis=0)
      maxDiff1, maxDiff2 = areaDiffs1.max(), areaDiffs2.max()

      # this loop may run for quite some time, keep GUI responsive by handling events
      keepGuiResponsiveAndRaiseIfSimulationDone()
      io.verb(f'refining UV-grid of finite area element sizes {len(U)=}, {len(V)=}, {maxDiff1=:.1e}, {maxDiff2=:.1e}')

      # end loop if biggest diff between neighboring area elements is <maxAreaElementDiff
      if max([maxDiff1, maxDiff2]) < maxAreaElementDiff:
        break

      # raise error if size of U,V mesh gets out of hand
      if max([len(U), len(V)]) > 1e4:
        raise ValueError(f'failed to sample UV mesh on face {face}, try relaxing the UVSamplingMaxRelAreaElementChange condition to higher values')

      # insert new U coordinates in ax=1
      if areaDiffs1.max() > areaDiffs2.max():
        maxI = argmax(areaDiffs1)
        iFrom = max([maxI-2, 0])
        iTo = min([maxI+3, len(areaDiffs1)])
        newU = linspace(U[iFrom], U[iTo], max([21, len(U)//4]) )
        if isclose(newU[1], newU[0], rtol=1e-9):
          raise ValueError(f'failed to sample UV mesh on face {face}, try relaxing the UVSamplingMaxRelAreaElementChange condition to higher values')
        U = concatenate([U[:iFrom], newU, U[iTo+1:]])
        
      # insert new V coordinates in ax=2
      else:
        maxI = argmax(areaDiffs2)
        iFrom = max([maxI-2, 0])
        iTo = min([maxI+3, len(areaDiffs2)])
        newV = linspace(V[iFrom], V[iTo], max([21, len(V)//4]) )
        if isclose(newV[1], newV[0], rtol=1e-9):
          raise ValueError(f'failed to sample UV mesh on face {face}, try relaxing the UVSamplingMaxRelAreaElementChange condition to higher values')
        V = concatenate([V[:iFrom], newV, V[iTo+1:]])

    # plot results for debugging
    #from matplotlib.pyplot import pcolormesh, show, xlabel, ylabel, colorbar, plot, figure
    #plot(V[:-1], areaDiffs2)
    #show()
    #figure()
    #pcolormesh(U, V, dA.T)
    #xlabel('u'); ylabel('v'); colorbar().set_label('dA')
    #show()
    return U, V, dA


  def _drawRandomPositionOnFace(self, obj, face):
    distTolerance = self._getDistTol()

    # keep rolling until we found a point on the surface
    while True:
      U, V, dA = self._sampleAreaElementsOnFace(obj, face)
      rv = distributions.SampledVectorRandomVariable(variableRanges=[U, V], gridProbs=dA, 
                                                    warnIfDiscretizationStepAbove=1)
      u, v = rv.draw()
      origin = face.valueAt(u, v)

      # only exit loop if u,v pair is actually located on face
      if Part.Vertex(origin).distToShape(face)[0] < distTolerance:
        break

      # this loop may run for quite some time, keep GUI responsive by handling events
      keepGuiResponsiveAndRaiseIfSimulationDone()

    du, dv = face.derivative1At(u, v)
    #print(f'{origin=}, {u=}, {v=}, {du=}, {dv=}')
    return origin, u, v, du, dv


  @functools.cache
  def _cachedSelectedFace(self, part, attrName):
    return getattr(cachedShape(part), attrName)


  def _generateRays(self, obj, mode, maxFanCount=inf, maxRaysPerFan=inf, **kwargs):
    '''
    This generator yields each ray to be traced for one simulation iteration.
    '''
    # calculate distance tolerance
    distTolerance = self._getDistTol()

    # make sure GUI does not freeze
    keepGuiResponsiveAndRaiseIfSimulationDone()

    # identify all faces that take part in the emission, split total 
    # emitted rays according to face area
    allFaces = []
    for (part, faces) in obj.ActiveSurfaces:
      if faces and len(faces):
        # if faces were explicitly selected, add them to total list
        selectedFaces = [self._cachedSelectedFace(part, f) for f in faces if f]
        if len(selectedFaces):
          allFaces.extend(selectedFaces)

        # if not faces were explicitly selected, add all faces of the body the list
        else:
          allFaces.extend(cachedFaces(cachedShape(part)))

    # calculate weight of each face by its area
    _allAreas = [f.Area for f in allFaces]
    allWeights = array(_allAreas)/sum(_allAreas)

    # fan-mode: generate rays with face-normal orientation and approximately uniform spacing on the surface
    if mode == 'fans':

      # determine how many rays to place in fan mode
      rayCountFanMode = obj.RayCountFanMode

      # function that rounds ray counts to integers 1, 4, 9 or greater
      # these are the reasonable numbers of rays to place per pace
      customRound = lambda x: round(x) if x>9 else [1,4,9][argmin(abs(x-array([1,4,9])))]

      # check if placing rays by weight but at least one per face exceeds
      # total ray count 
      _rayCount = sum([customRound(w*rayCountFanMode) for w in allWeights])
      skipFaceFraction = max([0, 1-rayCountFanMode/_rayCount])
      if skipFaceFraction > 0.3:
        warnings.warn(f'cannot place rays an all surfaces, because this would require to '
                      f'place {rayCount=} rays, which exceeds {rayCountFanMode=}. '
                      f'Skipping {1e2*skipFaceFraction:.0f}% of faces.')
      else:
        skipFaceFraction = 0

      # iterate over all weights and faces
      faceI = 0
      for weight, face in zip(allWeights, allFaces):

        # skip a portion of faces given by skipFaceFraction
        if skipFaceFraction > 0:
          _step = skipFaceFraction / weight*len(allFaces)
          if round(faceI) != round(faceI+_step):
            continue
          faceI += _step

        # decide how may rays to place, at low fidelity use either 1, 4, 9, after that increase smoothly
        raysOnFace = customRound(weight*rayCountFanMode)

        # generate grid of surface points attempting regular spacing
        io.verb(f'placing {raysOnFace=} rays on face {face}')
        for (u,v), point, (du,dv) in self._makeSurfaceGrid(obj, face, raysOnFace):
          yield self._makeRay(obj, 
                              origin=point, 
                              faceTangent=du if du.Length>10*distTolerance else [du,dv][argmax([du.Length, dv.Length])],
                              faceNormal=face.normalAt(u,v),
                              theta=0, phi=0)

    # true/pseudo random mode: place rays randomly distributed over the surface with 
    # angular distribution given by LocalPowerDensity
    elif mode == 'true' or mode == 'pseudo':

      # determine how many rays to place in one iteration
      raysPerIteration = 100
      if settings := find.activeSimulationSettings():
        raysPerIteration = settings.RaysPerIteration
      raysPerIteration *= obj.RaysPerIterationScale

      # prepare random variable
      vrv = self._getVrv(obj)

      # repeat raysPerIteration times
      for _ in range(int(round(raysPerIteration))):

        # randomly select face, weigh probability using face area
        face = random.choice(allFaces, p=allWeights)

        # roll random position on the selected surface
        origin, u, v, du, dv = self._drawRandomPositionOnFace(obj, face)

        # create/get random variable for theta and phi and draw samples 
        theta, phi = vrv.draw()

        # this loop may run for quite some time, keep GUI responsive by handling events
        keepGuiResponsiveAndRaiseIfSimulationDone()

        # create and return ray
        yield self._makeRay(obj, 
                            origin=origin, 
                            faceTangent=du if du.Length>10*distTolerance else [du,dv][argmax([du.Length, dv.Length])],
                            faceNormal=face.normalAt(u,v),
                            theta=theta, phi=phi)


#####################################################################################################
class SurfaceSourceViewProxy(GenericSourceViewProxy):
  pass

  
#####################################################################################################
class AddSurfaceSource(AddGenericSource):

  def Activated(self):
    # create new feature python object
    obj = App.activeDocument().addObject('App::LinkGroupPython', 'OpticalSurfaceSource')

    # create properties of object
    for section, entries in [
      ('OpticalEmission', [
        ('ActiveSurfaces', [], 'LinkSubList', 'List of surfaces that we want to emit rays from. '
                               'Selecting bodies without specifying individual faces implies '
                               'that all faces of the body emit.'),
        ('PowerDensity', 'cos(theta)', 'String',  
                  'Emitted optical power per solid angle at each surface element. '
                  'The expression may contain any mathematical '
                  'function contained in the numpy module and the polar angle "theta" '
                  'to make the emission of each surface element depend on the emission angle.'
                  'All rays placed by this light source begin on the selected surfaces.'),
        ('Wavelength', 500, 'Float', 'Wavelength of the emitted light in nm.'),
      ]),
      ('OpticalSimulationSettings', [
        *self.defaultSimulationSettings(obj),
        ('RandomNumberGeneratorMode', '?', 'String', ''),
        ('ThetaResolutionNumericMode', '1e6', 'String', ''),
        ('UVSamplingInitialResolution', '5', 'String', ''),
        ('UVSamplingMaxRelAreaElementChange', '0.1', 'String', ''),
        ('ThetaDomain', '0,pi/2', 'String', ''),
        ('RayCountFanMode', 100, 'Integer', 'Total number of rays to distribute over all '
                                 'emitting surfaces in fan mode.'),
       ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = SurfaceSourceProxy()
    if App.GuiUp:
      obj.ViewObject.Proxy = SurfaceSourceViewProxy()

    # make mode readonly
    obj.setEditorMode('RandomNumberGeneratorMode', 1)

    return obj

  def IsActive(self):
    return True

  def GetResources(self):
    return dict(Pixmap=self.iconpath(),
                Accel='',
                MenuText='Make point source',
                ToolTip='Add a point light source to the current project.')

def loadSurfaceSource():
  Gui.addCommand('Add surface source', AddSurfaceSource())
