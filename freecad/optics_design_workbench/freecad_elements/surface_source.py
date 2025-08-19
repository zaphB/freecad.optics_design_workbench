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
class SurfaceSourceProxy(GenericSourceProxy):

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    pass


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
    areaElems = [[ dp1*dp2 for dp1, dp2 in zip(dP1, dP2) ] for dP1, dP2 in zip(derivP1, derivP2) ]

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
    print(f'{paramOrder}, {paramSizes}')
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


  def _generateRays(self, obj, mode, maxFanCount=inf, maxRaysPerFan=inf, **kwargs):
    '''
    This generator yields each ray to be traced for one simulation iteration.
    '''
    # calculate distance tolerance
    distTolerance = self._getDistTol()

    # make sure GUI does not freeze
    keepGuiResponsiveAndRaiseIfSimulationDone()

    # fan-mode: generate fans of rays in spherical coordinates
    if mode == 'fans':

      # determine how many rays to place in fan mode
      rayCountFanMode = obj.RayCountFanMode

      # identify all faces that take part in the emission, split total 
      # emitted rays according to face area
      allFaces = []
      for (part, faces) in obj.ActiveSurfaces:
        if faces and len(faces):
          # if faces were explicitly selected, add them to total list
          selectedFaces = [getattr(part.Shape, f) for f in faces if f]
          if len(selectedFaces):
            allFaces.extend(selectedFaces)

          # if not faces were explicitly selected, add all faces of the body the list
          else:
            allFaces.extend(part.Shape.Faces)

      # calculate weight of each face by its area
      _allAreas = [f.Area for f in allFaces]
      allWeights = array(_allAreas)/sum(_allAreas)

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
        print(f'placing {raysOnFace=} rays on face {face}')
        for (u,v), point, (du,dv) in self._makeSurfaceGrid(obj, face, raysOnFace):
          yield self._makeRay(obj, 
                              origin=point, 
                              faceTangent=du if du.Length>10*distTolerance else [du,dv][argmax([du.Length, dv.Length])],
                              faceNormal=face.normalAt(u,v),
                              theta=0, phi=0)

    # true/pseudo random mode: place rays by drawing theta and phi from true random distribution
    elif mode == 'true' or mode == 'pseudo':

      # determine how many rays to place in one iteration
      raysPerIteration = 100
      if settings := find.activeSimulationSettings():
        raysPerIteration = settings.RaysPerIteration
      raysPerIteration *= obj.RaysPerIterationScale

      raise ValueError('not implemented')


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
        ('LocalPowerDensity', 'cos(theta)', 'String',  
                  'Emitted optical power per solid angle at each surface element. '
                  'The expression may contain any mathematical '
                  'function contained in the numpy module and the polar angle "theta" '
                  'to make the emission of each surface element depend on the emission angle.'
                  'All rays placed by this light source begin on the selected surfaces.'),
        ('Wavelength', 500, 'Float', 'Wavelength of the emitted light in nm.'),
      ]),
      ('OpticalSimulationSettings', [
        *self.defaultSimulationSettings(obj),
        ('ThetaRandomNumberGeneratorMode', '?', 'String', ''),
        ('ThetaResolutionNumericMode', '1e6', 'String', ''),
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
    obj.setEditorMode('ThetaRandomNumberGeneratorMode', 1)

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
