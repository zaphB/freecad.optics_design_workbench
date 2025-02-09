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

nx, ny, nz = array([1,0,0]), array([0,1,0]), array([0,0,1])


def planeProject3dPoints(points, planeNormal=None, returnZ=False):
  '''
  Turn a 3D point cloud of shape (N,3) into a 2D point cloud (N,2) 
  '''
  # detect plane normal if none is given explicitly
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


def detectPlaneNormal(points, maxPointCountConsidered=300, angleTol=1e-6):
  '''
  Find the best possible plane normal vector to project the 3D point cloud
  points to a 2D point cloud spanning a maximal area.
  '''
  checkPoints = points[::1+int(points.shape[0]/maxPointCountConsidered)]
  phis = linspace(0, pi/2, 10)
  dphi = phis[1]-phis[0]
  thetas = linspace(0, pi/2, 10)
  dtheta = thetas[1]-thetas[0]
  while True:
    # check all phi theta candidates and calculate expected span for them
    phiThetas, zSpans = [], []
    for phi, theta in zip(*[g.flatten() for g in meshgrid(phis, thetas)]):
      normal = array([cos(phi)*sin(theta), sin(phi)*sin(theta), cos(theta)])
      p = planeProject3dPoints(checkPoints, normal, returnZ=True)
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


def planarHistogram(data, XY='centers', key='points', planeNormal=None, **kwargs):
  '''
  Return the histogram of a 3D-point-cloud projected to a planeNormal. If planeNormal
  is not passed, a normal orthogonal to the two largest extents of the point could
  is chosen.
  Returns three rays: histogram, X and Y axes values. X and Y are either the bin edges
  (XY='edges') or the bin centers (XY='center')
  '''
  if type(data) is dict:
    points = data[key]
  else:
    points = data

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


def plotHits(hits, hueKey=None, hueLabel=None, planeNormal=None, plotKey='points', **kwargs):
  if planeNormal is None:
    planeNormal = detectPlaneNormal(hits[plotKey])
  X, Y = planeProject3dPoints(hits[plotKey], planeNormal=planeNormal).T
  data = {'projected x':X, 'projected y':Y}
  if hueKey is not None:
    if hueLabel is None:
      hueLabel = hueKey
    data[hueLabel] = hits[hueKey]
  nx, ny, nz = planeNormal
  sns.relplot(pd.DataFrame(data),
               x='projected x', y='projected y', 
               **(dict(hue=hueLabel, palette='hls') if hueLabel else {}),
               height=4)
  title(f'plane normal = [{nx:.2f}, {ny:.2f}, {nz:.2f}]', fontsize=10) 
  gca().axis('equal')
  gca().set_aspect('equal')
