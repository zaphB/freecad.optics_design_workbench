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

nx, ny, nz = array([1,0,0]), array([0,1,0]), array([0,0,1])

class Hits:
  def __init__(self, hits):
    self.hits = hits

  def points(self):
    if 'points' in self.hits:
      return self.hits['points']
    return array()

  # ====================================================
  # POINT CLOUD MATH

  def planeProject3dPoints(points=None, planeNormal=None, returnZ=False):
    '''
    Turn a 3D point cloud of shape (N,3) into a 2D point cloud (N,2) 
    '''
    # detect plane normal if none is given explicitly
    points = self.points()
    if planeNormal is None:
      planeNormal = detectPlaneNormal(points)

    # select projection vectors by cross products of normal with 
    # nx, ny and nz with highest norm 
    projX, projY = sorted([cross(planeNormal, n) for n in (nx, ny, nz)], 
                          key=lambda x: -linalg.norm(x))[:2]
    if returnZ:
      projZ = cross(projX, projY)
    X = dot(points, projX/linalg.norm(projX)) 
    Y = dot(points, projY/linalg.norm(projY))
    if returnZ:
      Z = dot(points, projZ/linalg.norm(projZ))
      return array([X, Y, Z]).T
    return array([X, Y]).T

  def detectPlaneNormal(maxPointCountConsidered=300, angleTol=1e-9):
    '''
    Find the best possible plane normal vector to project the 3D point cloud
    points to a 2D point cloud spanning a maximal area.
    '''
    points = self.points()
    checkPoints = points[::1+int(points.shape[0]/maxPointCountConsidered)]

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
        p = self.planeProject3dPoints(points=checkPoints, planeNormal=normal, returnZ=True)
        phiThetas.append((phi, theta))
        zSpans.append( (p[:,2].max()-p[:,2].min()) )

      # select phi thata with the best span so far and update grid
      phiOpt, thetaOpt = phiThetas[argmin(zSpans)]
      phis = linspace(phiOpt-1.1*dphi, phiOpt+1.1*dphi, 10)
      dphi = phis[1]-phis[0]
      thetas = linspace(thetaOpt-1.1*dtheta, thetaOpt+1.1*dtheta, 10)
      dtheta = thetas[1]-thetas[0]

      # quit loop if angle diff is smaller than tolerance
      if dphi < angleTol and dtheta < angleTol:
        break
    
    # set plane normal to optimal normal found so far
    return array([cos(phiOpt)*sin(thetaOpt), sin(phiOpt)*sin(thetaOpt), cos(thetaOpt)])

  def planarHistogram(XY='centers', key='points', planeNormal=None, **kwargs):
    '''
    Return the histogram of a 3D-point-cloud projected to a planeNormal. If planeNormal
    is not passed, a normal orthogonal to the two largest extents of the point could
    is chosen.
    Returns three rays: histogram, X and Y axes values. X and Y are either the bin edges
    (XY='edges') or the bin centers (XY='center')
    '''
    points = self.points()

    # if project vector is not given, set it to the direction of minimum span
    if planeNormal is None:
      planeNormal = detectPlaneNormal(points)

    # perform projection of full dataset
    projPoints = planeProject3dPoints(points, planeNormal)
    X, Y = projPoints.T

    # get histogram
    hist, binX, binY = histogram2d(X, Y, **kwargs)

    if XY == 'centers':
      binX = (binX[1:]+binX[:-1])/2
      binY = (binY[1:]+binY[:-1])/2
    elif XY == 'edges':
      pass
    else:
      raise ValueError(f'expected XY to be one of "edges" or "centers", found {XY=}')

    # return results
    return hist, binX, binY

  def plot(hueKey=None, hueLabel=None, planeNormal=None, plotKey='points', **kwargs):
    hits
    if planeNormal is None:
      planeNormal = detectPlaneNormal(self.hits[plotKey])
    X, Y = planeProject3dPoints(self.hits[plotKey], planeNormal=planeNormal).T
    data = {'projected x':X, 'projected y':Y}
    if hueKey is not None:
      if hueLabel is None:
        hueLabel = hueKey
      data[hueLabel] = self.hits[hueKey]
    nx, ny, nz = planeNormal
    sns.relplot(pd.DataFrame(data),
                x='projected x', y='projected y', 
                **(dict(hue=hueLabel, palette='hls') if hueLabel else {}),
                height=4)
    title(f'plane normal = [{nx:.2f}, {ny:.2f}, {nz:.2f}]', fontsize=10) 
    gca().axis('equal')
    gca().set_aspect('equal')

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
    return len(set(self.hits['fanIndex']))

  @functools.cache
  def _calcFanDensityEtc(self, **kwargs):
    self._raiseIfNotFanMath()

    rI, fI, p, trf = self.hits['rayIndex'], self.hits['fanIndex'], self.hits['points'], self.hits['totalRaysInFan']
    pXY = planeProject3dPoints(p, **kwargs)

    # loop trough fans/rays and calculate distance, curvature etc.
    centerDists, neighborDists = [], []
    curvs, missingRays, skippedRays = [], 0, 0
    for fanI in sorted(list(set(fI))):
      prevPrevPos = None
      prevPos = None
      rayIs = sorted(list(set(rI[fI==fanI])))

      # find most central ray
      centerI = rayIs[argmin(abs(rayIs))]
      pCenter = mean(pXY[logical_and(fI==fanI, rI==centerI)], axis=0)

      # increment missing rays
      missingRays += mean(trf[fI==fanI])-len(rayIs)
      skippedRays += sum(array(rayIs[1:])-array(rayIs[:-1]) - 1)

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
          centerDists.append( [ fanI, i0, dCenter*sign(i0-centerI) ] )

        # calc distance of p0 to line through p1,p2
        if i0 is not None and i1 is not None and i2 is not None:
          (x0, y0), (x1, y1), (x2, y2) = (p0, p1, p2)
          curvs.append( [ fanI, i0, abs( (y2-y1)*x0 - (x2-x1)*y0 + x2*y1 - y2*x1 ) / sqrt((y2-y1)**2 + (x2-x1)**2) ] )

    # return as dict
    return dict(centerDists=array(centerDists), neighborDists=array(neighborDists), 
                curvs=array(curvs), missingRays=missingRays, skippedRays=skippedRays)

  def fanMissingRays():
    return _calcFanDensityEtc()['missingRays']

  def fanSkippedRays():
    return _calcFanDensityEtc()['skippedRays']

  def fanCenterDists():
    return _calcFanDensityEtc()['centerDists'].T

  def fanNeighborDists():
    return _calcFanDensityEtc()['neighborDists'].T

  def fanCurvs():
    return _calcFanDensityEtc()['curvs'].T
