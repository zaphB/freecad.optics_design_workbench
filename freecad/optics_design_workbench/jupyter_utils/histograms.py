from numpy import *

nx, ny, nz = array([1,0,0]), array([0,1,0]), array([0,0,1])

def projectPointCloud(points, planeNormal):
  '''
  Turn a 3D point cloud of shape (N,3) into a 2D point cloud (N,2) 
  '''
  # select projection vectors by cross products of normal with 
  # nx, ny and nz with highest norm 
  projX, projY = sorted([cross(planeNormal, n) for n in (nx, ny, nz)], 
                        key=lambda x: -linalg.norm(x))[:2]
  X = dot(points, projX/linalg.norm(projX)) 
  Y = dot(points, projY/linalg.norm(projY))
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
    phiThetas, spans = [], []
    for phi, theta in zip(*[g.flatten() for g in meshgrid(phis, thetas)]):
      normal = array([cos(phi)*sin(theta), sin(phi)*sin(theta), cos(theta)])
      p = projectPointCloud(checkPoints, normal)
      phiThetas.append((phi, theta))
      spans.append( (p[:,0].max()-p[:,0].min()) * (p[:,1].max()-p[:,1].min()) )

    # select phi thata with the best span so far and update grid
    phiOpt, thetaOpt = phiThetas[argmax(spans)]
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
  points = data[key]

  # if project vector is not given, set it to the direction of minimum span
  if planeNormal is None:
    planeNormal = detectPlaneNormal(points)

  # perform projection of full dataset
  projPoints = projectPointCloud(points, planeNormal)
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
