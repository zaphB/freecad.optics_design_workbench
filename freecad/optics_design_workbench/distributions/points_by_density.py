'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from matplotlib.pyplot import *
from numpy import *

def calcHistDensity(X, bins=None):
  H, bins = histogram(X, **({} if bins is None 
                              else {'bins':bins}))
  return (bins[1:]+bins[:-1])/2, H/sum(H)
  
def calcDiffDensity(X):
  X = array(sorted(X))
  diffs = X[1:]-X[:-1]
  density = 1/(maximum(diffs, 1e-30))
  return (X[1:]+X[:-1])/2, density/sum(density)

def generatePointsWithGivenDensity1D(density, N, startFrom=None):
  # do numeric integration and normalize result to [0,1] interval
  X, Y = density
  Xi = concatenate([ [X[0]-(X[1]-X[0])/2], 
                     (X[:-1]+X[1:])/2, 
                     [X[-1]+(X[-1]-X[-2])/2] ])
  Yi = concatenate([[0],cumsum(Y)])
  Yi = (Yi-Yi.min())/(Yi.max()-Yi.min())

  # pick values from X according to inverse Yi->X mapping,
  # generate two values more than requested and strip outermost 
  # two in result to get rid of edge-errors
  Ypick = linspace(0, 1, int(round(N)))[1:-1]
  return concatenate([[X[0]], interp(Ypick, Yi, Xi), [X[-1]]])


def generatePointsWithGivenDensity2D(density, N):
  # idea: start with empty list,
  # 1) calc 2D histogram with slightly randomized bins 
  #    to avoid bin edge artifacts
  #     -> if point count and histogram deviation from target
  #        are ok, return 
  # 2) find place with highest deviation from required histogram
  # 3) add sample there
  # 4) continue from 1)
  raise RuntimeError('not implemented')
