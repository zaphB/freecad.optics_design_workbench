'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from .point_clouds import *


def calcFanPolarHitPositions(hits, **kwargs):
  # extract used arrays
  try:
    rI, fI, p, trf = hits['rayIndex'], hits['fanIndex'], hits['points'], hits['totalRaysInFan']
  except KeyError:
    raise ValueError(f'keys rayIndex, fanIndex and totalRaysInFan must exist in hits dictionary, '
                     f'make sure you '
                     f'simulated in fan mode and enabled storing the respective metadata keys '
                     f'in the active SimulationSettings')
  pXY = planeProject3dPoints(p, **kwargs)

  # loop through fans/rays and calculate distance, curvature etc.
  fans, rays, centerDists, missingRays, skippedRays = [], [], [], 0, 0
  for fanI in sorted(list(set(fI))):
      prevPrevPos = None
      prevPos = None
      rayIs = array(sorted(list(set(rI[fI==fanI]))))

      # find most central ray
      centerI = rayIs[argmin(abs(rayIs))]
      pCenter = mean(pXY[logical_and(fI==fanI, rI==centerI)], axis=0)

      # increment missing rays
      missingRays += mean(trf[fI==fanI])-len(rayIs)
      skippedRays += sum(rayIs[1:]-rayIs[:-1] - 1)

      # loop through ray-trios to calculate neighbor dists and curvs
      for i0 in rayIs:
          fans.append(fanI)
          rays.append(i0)
          # calc distances
          p0, = [mean(pXY[logical_and(fI==fanI, rI==i)], axis=0) for i in (i0,)]
          dCenter, = [sqrt(sum((_p-__p)**2)) for _p,__p in ([p0,pCenter],)]
          centerDists.append( dCenter*sign(i0-centerI) )

  # return as dict
  return dict(fans=array(fans), rays=array(rays), centerDists=array(centerDists), 
              missingRays=missingRays, skippedRays=skippedRays)


def calcFanDensity(hits, **kwargs):
  # extract used arrays
  try:
    rI, fI, p, trf = hits['rayIndex'], hits['fanIndex'], hits['points'], hits['totalRaysInFan']
  except KeyError:
    raise ValueError(f'keys rayIndex, fanIndex and totalRaysInFan must exist in hits dictionary, '
                     f'make sure you '
                     f'simulated in fan mode and enabled storing the respective metadata keys '
                     f'in the active SimulationSettings')
  pXY = planeProject3dPoints(p, **kwargs)

  # loop through fans/rays and calculate distance, curvature etc.
  fans, rays, neighborDists, centerDists, curvs, missingRays, skippedRays = [], [], [], [], [], 0, 0
  for fanI in sorted(list(set(fI))):
      prevPrevPos = None
      prevPos = None
      rayIs = array(sorted(list(set(rI[fI==fanI]))))

      # find most central ray
      centerI = rayIs[argmin(abs(rayIs))]
      pCenter = mean(pXY[logical_and(fI==fanI, rI==centerI)], axis=0)

      # increment missing rays
      missingRays += mean(trf[fI==fanI])-len(rayIs)
      skippedRays += sum(rayIs[1:]-rayIs[:-1] - 1)

      # loop through ray-trios to calculate neighbor dists and curvs
      for i1, i0, i2 in zip(rayIs[:-2], rayIs[1:-1], rayIs[2:]):        
          fans.append(fanI)
          rays.append(i0)
          p0, p1, p2 = [mean(pXY[logical_and(fI==fanI, rI==i)], axis=0) for i in (i0, i1, i2)]
          (x0, y0), (x1, y1), (x2, y2) = (p0, p1, p2)
          
          # calc distances
          d1, d2, dCenter = [sqrt(sum((_p-__p)**2)) for _p,__p in ([p0,p1], [p0,p2], [p0,pCenter])]
          neighborDists.append( d1/2+d2/2 )
          centerDists.append( dCenter*sign(i0-centerI) )

          # calc distance of p0 to line through p1,p2
          curvs.append( abs( (y2-y1)*x0 - (x2-x1)*y0 + x2*y1 - y2*x1 ) / sqrt((y2-y1)**2 + (x2-x1)**2) )

  # return as dict
  return dict(fans=array(fans), rays=array(rays), centerDists=array(centerDists), 
              neighborDists=array(neighborDists), curvs=array(curvs), 
              missingRays=missingRays, skippedRays=skippedRays)


def plotFanDensity(density):
  fans, rays, cdists, ndists, curvs = [density[k] for k in 'fans rays centerDists neighborDists curvs'.split()]
  d = pd.DataFrame(zip(*[fans, rays, cdists, ndists, curvs]),
                columns=['fan #', 'ray #', 'distance from center',
                          'hit neighbor distance', 'hit neighbor curvature'])
  d = d.melt(id_vars=['fan #', 'ray #'])
  g = sns.relplot(d, x='ray #', y='value', hue='fan #', col='variable', facet_kws=dict(sharey=False), height=3)
  for ax, t in zip(g.axes.flatten(), ['distance from center', 'hit neighbor distance', 'hit neighbor curvature']):
      ax.set(title='', ylabel=t)
  g.tight_layout()
