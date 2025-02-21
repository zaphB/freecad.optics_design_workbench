'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
from matplotlib.pyplot import *
import seaborn as sns
import pandas as pd
import functools

from .. import io
from . import histogram

nx, ny, nz = array([1,0,0]), array([0,1,0]), array([0,0,1])

class Hits:
  def __init__(self, hits):
    self.hits = hits

  def __iter__(self):
    return self.hits.keys()

  def __len__(self):
    return len(self.points())

  def items(self):
    return self.hits.items()

  def keys(self):
    return self.hits.keys()

  def values(self):
    return self.hits.values()

  def points(self):
    if 'points' in self.hits:
      return self.hits['points']
    return array([])

  def directions(self):
    if 'directions' in self.hits:
      return self.hits['directions']
    return array([])

  def isEntering(self):
    if 'isEntering' in self.hits:
      return self.hits['isEntering']
    return array([])

  # ====================================================
  # POINT CLOUD MATH

  def planeProject3dPoints(self, points=None, planeNormal=None, 
                           inPlaneXDir=None, returnZ=False):
    '''
    Turn a 3D point cloud of shape (N,3) into a 2D point cloud (N,2).

    Parameters:
      points : (N,3) array (optional)
        Point cloud to project, defaults to self.points().

      planeNormal : (3,) array (optional)
        Normal vector of the projection plane, defaults to result
        of detectPlaneNormal(points).

      inPlaneXDir : (3,) array (optional)
        Vector pointing into the desired X-coordinate direction of
        the coordinate system after projection. Defaults to the 
        numerically best suited vector among (1,0,0), (0,1,0) and (0,0,1).
    '''
    # detect plane normal if none is given explicitly
    if points is None:
      points = self.points()
    if planeNormal is None or inPlaneXDir is None:
      planeNormal, inPlaneXDir = self.detectPlaneNormal(planeNormal=planeNormal, 
                                                        inPlaneXDir=inPlaneXDir)

    projX = inPlaneXDir
    X = dot(points, projX/linalg.norm(projX)) 
    projY = cross(planeNormal, inPlaneXDir)
    Y = dot(points, projY/linalg.norm(projY))
    if returnZ:
      Z = dot(points, planeNormal/linalg.norm(planeNormal))
      return array([X, Y, Z]).T
    return array([X, Y]).T

  def detectPlaneNormal(self, points=None, directions=None, 
                        planeNormal=None, inPlaneXDir=None,
                        maxPointCountConsidered=300, angleTol=1e-9):
    '''
    Find the best possible plane normal vector to project the 3D point cloud
    points to a 2D point cloud spanning a maximal area.
    '''
    if points is None:
      points = self.points()
    if directions is None:
      directions = self.directions()
      isEntering = self.isEntering()
      # remove directions of exiting rays when more rays entered than exited
      # -> heuristic to improve planeNormal sign auto-detect for transparent detectors
      if sum(isEntering==0) < .51*len(isEntering):
        directions = directions[isEntering!=0]
    checkPoints = points[::1+int(points.shape[0]/maxPointCountConsidered)]
    checkDirections = directions[::1+int(directions.shape[0]/maxPointCountConsidered)]

    if planeNormal is None:
      # cover only half the unit sphere because every plane has two normal
      # vectors (sign is ambiguous)
      phis = linspace(0, pi, 30)
      dphi = phis[1]-phis[0]
      thetas = linspace(-pi/2, pi/2, 30)
      dtheta = thetas[1]-thetas[0]
      while True:
        # check all phi theta candidates and calculate expected span for them
        phiThetas, zSpans = [], []
        for phi, theta in zip(*[g.flatten() for g in meshgrid(phis, thetas)]):
          normal = array([cos(phi)*sin(theta), sin(phi)*sin(theta), cos(theta)])
          p = dot(checkPoints, normal)
          phiThetas.append((phi, theta))
          zSpans.append( p.max()-p.min() )

        # select phi thata with the best span so far and update grid
        phiOpt, thetaOpt = phiThetas[argmin(zSpans)]
        phis = linspace(phiOpt-1.1*dphi, phiOpt+1.1*dphi, 10)
        dphi = phis[1]-phis[0]
        thetas = linspace(thetaOpt-1.1*dtheta, thetaOpt+1.1*dtheta, 10)
        dtheta = thetas[1]-thetas[0]

        # quit loop if angle diff is smaller than tolerance
        if dphi < angleTol and dtheta < angleTol:
          break

      # calc best planeNormal
      planeNormal = array([cos(phiOpt)*sin(thetaOpt), sin(phiOpt)*sin(thetaOpt), cos(thetaOpt)])

    # choose planeNormal sign to be parallel with directions as well as possible
    projectedDirs = dot(checkDirections, planeNormal)
    # 90% of directions are same direction as planeNormal -> flip plane normal
    if quantile(projectedDirs, 0.1) > 0:
      planeNormal = -planeNormal
    # 90% of directions are opposite direction of planeNormal -> all good
    elif quantile(projectedDirs, 0.9) < 0:
      pass
    # something in between: follow best guess and warn user
    else:
      if quantile(projectedDirs, 0.5) < 0:
        planeNormal = -planeNormal
      io.warn(f'unsure of result when trying to auto-detect sign of plane normal, '
              f'avoid relying on the sign of the planeNormal')

    # select projection vectors by cross products of normal with 
    # nx, ny and nz with highest norm to ensure numeric stability
    # if planeNormal is almost parallel to one of nx, ny or nz.
    candidates = [nx, ny, nz]
    if inPlaneXDir is not None:
      candidates = [inPlaneXDir]
    projY = sorted([cross(planeNormal, n) for n in candidates], 
                   key=lambda x: -linalg.norm(x))[0]
    inPlaneXDir = cross(planeNormal, projY)
    # prefer positive coefficients in inPlaneXDir
    if sum(inPlaneXDir) < 0:
      inPlaneXDir = -inPlaneXDir

    # set plane normal to optimal normal found so far
    return planeNormal, inPlaneXDir

  def histogram(self, planeNormal=None, inPlaneXDir=None, key='points', **kwargs):
    '''
    Return the histogram of a 3D-point-cloud projected to a planeNormal. If planeNormal
    is not passed, a normal orthogonal to the two largest extents of the point could
    is chosen.
    Returns three rays: histogram, X and Y axes values. X and Y are either the bin edges
    (XY='edges') or the bin centers (XY='center')
    '''
    points = self.hits[key]

    # if project vector is not given, set it to the direction of minimum span
    if planeNormal is None or inPlaneXDir is None:
      planeNormal, inPlaneXDir = self.detectPlaneNormal(planeNormal, inPlaneXDir)

    # perform projection of full dataset
    projPoints = self.planeProject3dPoints(points, planeNormal=planeNormal, inPlaneXDir=inPlaneXDir)
    X, Y = projPoints.T
    return histogram.Histogram(X, Y, planeNormal=planeNormal, inPlaneXDir=inPlaneXDir, **kwargs)


  def plot(self, hueKey=None, hueLabel=None, planeNormal=None, inPlaneXDir=None, 
           plotKey='points', **kwargs):
    # just return if no hits exist
    if plotKey not in self.hits.keys():
      return

    if planeNormal is None or inPlaneXDir is None:
      planeNormal, inPlaneXDir = self.detectPlaneNormal(points=self.hits[plotKey], 
                                    planeNormal=planeNormal, inPlaneXDir=inPlaneXDir)
    X, Y = self.planeProject3dPoints(self.hits[plotKey], planeNormal=planeNormal).T
    data = {'projected $x$':X, 'projected $y$':Y}
    if hueKey is not None:
      if hueLabel is None:
        hueLabel = hueKey
      data[hueLabel] = self.hits[hueKey]
    sns.scatterplot(pd.DataFrame(data),
                    x='projected $x$', y='projected $y$', 
                    **(dict(hue=hueLabel, palette='hls') if hueLabel else {}),
                    **kwargs)
    nx, ny, nz = planeNormal
    px, py, pz = inPlaneXDir
    title(f'plane normal = [{nx:.2f}, {ny:.2f}, {nz:.2f}],\n'
          f'projected $x$ = [{px:.2f}, {py:.2f}, {pz:.2f}]', fontsize=10) 
    gca().axis('equal')
    gca().set_aspect('equal')
    tight_layout()

  # ====================================================
  # FAN MATH

  def supportsFanMath(self):
    return all([k in self.hits.keys() for k in 'rayIndex fanIndex totalRaysInFan'.split()])

  def _raiseIfNotFanMath(self):
    if not self.supportsFanMath():
      raise ValueError(f'keys rayIndex, fanIndex and totalRaysInFan must exist in hits dictionary, '
                f'make sure you '
                f'simulated in fan mode and enabled storing the respective metadata keys '
                f'in the active SimulationSettings')

  def raysPerFan(self):
    self._raiseIfNotFanMath()
    return self.hits['totalRaysInFan'][0]

  def fanCount(self):
    self._raiseIfNotFanMath()
    return len(set(self.hits['fanIndex']))

  @functools.cache
  def _calcFanDensityEtc(self, pCenter=None, **kwargs):
    self._raiseIfNotFanMath()

    rI, fI, p, trf = self.hits['rayIndex'], self.hits['fanIndex'], self.hits['points'], self.hits['totalRaysInFan']
    pXY = self.planeProject3dPoints(p, **kwargs)

    # loop trough fans/rays and calculate distance, curvature etc.
    centerDists, neighborDists = [], []
    curvs, missingRays, skippedRays = [], 0, 0
    for fanI in sorted(list(set(fI))):
      prevPrevPos = None
      prevPos = None
      rayIs = sorted(list(set(rI[fI==fanI])))

      # find most central ray
      centerI = rayIs[argmin(abs(array(rayIs)))]
      if pCenter is None:
        pCenter = mean(pXY[logical_and(fI==fanI, rI==centerI)], axis=0)
      pCenter = array(pCenter)

      # increment missing rays
      missingRays += mean(trf[fI==fanI])-len(rayIs)
      skippedRays += sum(array(rayIs[1:])-array(rayIs[:-1]) - 1)

      # find most likely vectors of positive and negative ray index direction
      _posIndexVectors = pXY[logical_and(fI==fanI, rI>0)]-pCenter
      posIndexDirection = None
      if len(_posIndexVectors):
        _norms = sqrt(sum(_posIndexVectors**2, axis=0))
        _norms[_norms==0] = 1
        posIndexDirection = mean(_posIndexVectors/_norms, axis=0)
      _negIndexVectors = pXY[logical_and(fI==fanI, rI<0)]-pCenter
      negIndexDirection = None
      if len(_negIndexVectors):
        _norms = sqrt(sum(_negIndexVectors**2, axis=0))
        _norms[_norms==0] = 1
        negIndexDirection = mean(_negIndexVectors/_norms, axis=0)

      # fill missing directions with respective other of opposite sign
      if posIndexDirection is None and negIndexDirection is None:
        posIndexDirection = array([1,0])
        negIndexDirection = array([-1,0])
      elif posIndexDirection is None:
        posIndexDirection = -negIndexDirection
      elif negIndexDirection is None:
        negIndexDirection = -posIndexDirection

      # loop trough ray-trios to calculate neighbor dists and curvs
      for i1, i0, i2 in zip(rayIs+[None,None], [None]+rayIs+[None], [None,None]+rayIs):        

        # calc points and distances
        p0, p1, p2 = [None if i is None else mean(pXY[logical_and(fI==fanI, rI==i)], axis=0) 
                                                                      for i in (i0, i1, i2)]
        d1, d2, dCenter = [None if _p is None or __p is None else  sqrt(sum((_p-__p)**2)) 
                                              for _p,__p in ([p0,p1], [p0,p2], [p0,pCenter])]

        # add neighbor and center dist entries
        if d1 is not None:
          neighborDists.append( [ fanI, (i0+i1)/2, d1 ] )
        if i0 is not None:
          # decide about dCenterSign
          signP, signN = dot(p0-pCenter, posIndexDirection), dot(p0-pCenter, negIndexDirection)
          if signP > 0 and signN < 0:
            dCenterSign = +1
          elif signP < 0 and signN > 0:
            dCenterSign = -1
          else:
            #if signN != 0 and signP != 0:
            #  io.warn(f'unsure about center distance value signs, the fan-hit pattern is probably '
            #          f'very asymmetric ({dot(p0-pCenter, posIndexDirection)=}, {dot(p0-pCenter, negIndexDirection)=})')
            dCenterSign = sign( signP - signN )

          # add center dist entry
          centerDists.append( [ fanI, i0, dCenter*dCenterSign ] )

        # calc distance of p0 to line through p1,p2
        if i0 is not None and i1 is not None and i2 is not None:
          (x0, y0), (x1, y1), (x2, y2) = (p0, p1, p2)
          curvs.append( [ fanI, i0, abs( (y2-y1)*x0 - (x2-x1)*y0 + x2*y1 - y2*x1 ) / sqrt((y2-y1)**2 + (x2-x1)**2) ] )

    # return as dict
    return dict(centerDists=array(centerDists), neighborDists=array(neighborDists), 
                curvs=array(curvs), missingRays=missingRays, skippedRays=skippedRays)

  def fanMissingRays(self):
    return self._calcFanDensityEtc()['missingRays']

  def fanSkippedRays(self):
    return self._calcFanDensityEtc()['skippedRays']

  def fanCenterDists(self, pCenter=None):
    return self._calcFanDensityEtc(pCenter=(tuple(pCenter) if pCenter else None))['centerDists'].T

  def fanNeighborDists(self):
    return self._calcFanDensityEtc()['neighborDists'].T

  def fanCurvs(self):
    return self._calcFanDensityEtc()['curvs'].T
