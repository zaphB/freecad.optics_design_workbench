__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

'''.strip()


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

def _generatePointsCandidate(density, scale, N, initialize, refineIters, startFrom=None):
  _mean = lambda A: mean(A) if len(A) else nan

  # generate candidate for points following density given
  # by density with distances scaled by scale
  X, Y = density
  
  # extend X and Y for easier interploation
  dX1, dX2 = X[1]-X[0], X[-1]-X[-2]
  Xs = max(X)-min(X)
  lPad = arange(X[0]-dX1, X[0]-10*Xs, -dX1)[::-1]
  rPad = arange(X[-1]+dX2, X[-1]+10*Xs, dX2)
  Xext = concatenate([lPad, X, rPad])
  Yext = concatenate([[Y[0]]*len(lPad), Y, [Y[-1]]*len(rPad)])
  
  scale = max([scale, 1e-30])
  if startFrom is None:
    startFrom = X[argmax(Y)]

  if initialize == 'step':
    # find initial guess by stepping from global maximum
    # with stepsizes following desired density, works very
    # well for single-peaked distributions
    R = [startFrom]
    while R[-1] <= max(X)+5*(max(X)-min(X)) and len(R)<10*N:
      i1 = i2 = argmin(abs(Xext-R[-1]))
      lastStep = None
      stepCandidates = []
      for remaining in reversed(range(100)):
        stepCandidates.append(scale/max([_mean(abs(Yext[i1:i2+1])), 1e-30]))
        stepCandidates = stepCandidates[-1-remaining:]
        step = mean(stepCandidates)
        i2 = argmin(abs(Xext-(R[-1]+step)))
        if len(stepCandidates) < 5 and lastStep is not None and abs(step-lastStep)/step < min([1/N, 1e-3]):
          break
        lastStep = step
      R.append(R[-1]+step)
    L = [startFrom]
    while L[-1] >= min(X)-5*(max(X)-min(X)) and len(L)<10*N:
      i1 = i2 = argmin(abs(Xext-L[-1]))
      lastStep = None
      stepCandidates = []
      for remaining in reversed(range(100)):
        stepCandidates.append(scale/max([_mean(abs(Yext[i2:i1+1])), 1e-30]))
        stepCandidates = stepCandidates[-1-remaining:]
        step = mean(stepCandidates)
        i2 = argmin(abs(Xext-(L[-1]-step)))
        if len(stepCandidates) < 5 and lastStep is not None and abs(step-lastStep)/step < min([1/N, 1e-3]):
          break
        lastStep = step
      L.append(L[-1]-step)
    L = L[1:][::-1]
    result = array(L+R)
    
  # useless as long as refinement does not work well
  elif initialize == 'linspace':
    # find initial guess just by placing linspaced values
    # needs a lot of refinement but does not get confused
    # by multiple maxima or noisy distributions
    result = linspace(min(X)-5*(max(X)-min(X)),
                      max(X)+5*(max(X)-min(X)),
                      10*N*scale)
  else:
    raise ValueError(f'unknown initialize method {initialize}')
  
  #    refining driven by error gradients does not really work, 
  #    probably a Monte-Carlo approach is needed...
  # check how close candidate is to target and refine positions
  #plotI = 0
  #plot(result, [0]*len(result), 'o')
  rmsErr = inf
  if len(result) > 3:
    #print('-'*30)
    def _getErrs(_X):
      dX, dD = calcDiffDensity(_X)
      densityErr = dD - array([_mean(Yext[logical_and(x1<Xext,Xext<x2)])
                          for x1,x2 in zip(_X[:-1], _X[1:])])
      # treat nans and infs as zero error
      densityErr[logical_not(isfinite(densityErr))] = 0
      # append two zeros to also move outmost result points
      densityErr = concatenate([[0], densityErr, [0]])
      rmsErr = mean(densityErr**2)
      return densityErr, rmsErr
      
    _refineScale = 0.1
    for _ in range(refineIters):
    #while True:
      if len(result) <= 3:
        break
    
      densityErr, rmsErr = _getErrs(result)
      
      # calc error differences, has same shape as result now
      errDeriv = densityErr[1:]-densityErr[:-1]

      # normalize derivative scale to neighbor distance scale
      approxNeighborDist = concatenate([
                                  [abs(result[1]-result[0])], 
                                  abs(result[2:]-result[:-2])/2, 
                                  [abs(result[-1]-result[-2])]])
      _result = (result - _refineScale 
                          * errDeriv/max(abs(errDeriv))
                          * approxNeighborDist )
      # strip datapoints that might have been pushed out of range
      _result = _result[logical_and(min(Xext)<_result,_result<max(Xext))]
      #plot(_result, [plotI]*len(result), 'o', ms=5)
      #plotI += 1

      # test whether result improved
      _, newRmsErr = _getErrs(_result)
      #print(f'{newRmsErr=}')
      if newRmsErr < rmsErr:
        result = _result
      else:
        _refineScale *= 0.8
            
      # update _refine scale
      relErrChange = abs(newRmsErr-rmsErr)/max([rmsErr,1e-30])
      #print(f'{relErrChange=}')
      if relErrChange < 1e-2:
        _refineScale *= 1.5
      if relErrChange > 10e-2:
        _refineScale *= 0.6
      
      # clip _refine scale at 0.1
      _refineScale = min([_refineScale, 0.1])
  
  # crop at X range +/- 10%
  result = result[logical_and(
                    result>=min(X)-0.1*(max(X)-min(X)), 
                    result<=max(X)+0.1*(max(X)-min(X)))]
    
  return result, rmsErr


def generatePointsWithGivenDensity1D(density, N, startFrom=None):
  # normalize density
  X, Y = density
  density = X, Y/sum(Y)
    
  # find correct scale to achieve approx N points
  Xbest = None
  errBest = None
  for init in ('step',): #'linspace'):
    scale = 1
    for exponent in linspace(1, 0.1, 50):
      Xcan, err = _generatePointsCandidate(density, scale=scale, 
                                      N=N, initialize=init,
                                      refineIters=0,
                                      startFrom=startFrom)
      scale *= ( len(Xcan)/N )**exponent
      if (abs(len(Xcan)-N)-3)/max([N,1]) < 1e-2:
        break
    if errBest is None or err < errBest:
      errBest = err
      Xbest = Xcan

  if Xbest is None:
    raise ValueError('could not find solution')

  # return best candidate
  return Xbest


def generatePointsWithGivenDensity2D(density, N):
  # idea: start with empty list,
  # 1) calc 2D histogram with slightly randomized bins 
  #    to avoid bin edge artifacts
  #     -> if point count and histogram deviation from target
  #        are ok, return 
  # 2) find place with highest deviation from required histogram
  # 3) add sample there
  # 4) continue from 1)
  pass
