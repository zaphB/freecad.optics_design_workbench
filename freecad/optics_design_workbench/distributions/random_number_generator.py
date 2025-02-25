'''
Classes to generate random numbers according to arbitrary probability distribution functions.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

# make sure bool() is not overloaded by numpy import
_bool = bool
from numpy import *
bool = _bool

import sympy as sy
import time
import signal

from . import points_by_density
from .. import io


def _setAlarm(deadline):
    timeout = deadline-time.time()
    # it may seem a bit drastic to raise a KeyboardInterrupt here, but other Exceptions
    # seem to be caught by sympy internally in certain cases. Only KeyboardInterrupt
    # is able to actually stop a hung sympy function.
    if timeout < 0:
      raise KeyboardInterrupt('time is up')
    def handler(sig, n):
      raise KeyboardInterrupt('time is up')
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(int(timeout)+1)


def _clearAlarm():
  signal.alarm(0)


class VectorRandomVariable:
  '''
  Vector valued random variable. 
  '''
  def __init__(self, probabilityDensity, variableDomains={}, numericalResolutions={}, variableOrder=None,
               warnIfDiscretizationStepAbove=5e-2):
    self._probabilityDensity = probabilityDensity
    self._probabilityDensityBaseExpr = None
    self._variables = None
    self._variableDomains = variableDomains
    self._numericalResolutions = numericalResolutions
    self._variableOrder = variableOrder
    self._constantsDict = {}
    self._mode = 'not yet compiled'
    self._warnIfDiscretizationStepAbove = warnIfDiscretizationStepAbove


  def compile(self, timeout=2, disableAnalytical=False, **kwargs):
    '''
    Draw random numbers (or vectors) following the distribution represented by this object.

    Arguments:
    ==========
    timeout : numeric
      Give up on finding an analytical solution and fallback to numeric mode after timeout seconds.

    disableAnalytical : boolean
      Set to true to completely disable analytic mode.

    **kwargs    
      Dictionary of constants to substitute in the distribution expression.
    '''
    self._deadline = time.time()+timeout
    self._setConstants(**kwargs)

    try:
      # immediately go to numerical fallback if analytical is disabled
      if disableAnalytical:
        raise ValueError('stop')

      # try analytical treatment first
      self._transformLambdas = [self._generateAnalyticScalarLambda(i) for i in range(len(self._variables))]
      self._mode = 'analytic'

    # fallback to numerical treatment and analytical mode did not succeed
    except Exception:
      self._transformLambdas = [self._generateNumericScalarLambda(i) for i in range(len(self._variables))]
      self._mode = 'numeric'


  def mode(self):
    return self._mode


  def showExpressions(self, simplify=True):
    '''
    Pretty print generated internal expressions and lambdas for debugging purposes.
    '''
    print('probability density expression: ', self._probabilityDensityExpr, ' variables: ', self._variables)
    print(self._transformLambdas)
    for i, var in enumerate(self._variables):
      print(f'variable "{var}" '+('conditional' if i<len(self._variables)-1 else '')+f' probability density: ')
      probDens, integral, invertedSols = self._transformLambdas[i][0]._origExpressions
      if simplify and str not in [type(x) for x in (probDens, integral, invertedSols)]:
        probDens = probDens.simplify()
        integral = integral.simplify()
        invertedSols = [sol.simplify() for sol in invertedSols]
      print(f'  conditional prop. dens.: ', probDens)
      print(f'  integrated prop. dens.: ', integral)
      if len(invertedSols) > 1:
        print(f'  inverted integral solutions: ')
        for sol in invertedSols:
          print('    ', sol)
      else:
        print(f'  inverted integral solution: ', invertedSols[0])


  def _setConstants(self, **kwargs):
    # store passed constants dictionary for later reference
    self._constantsDict = kwargs

    # prepare expression object
    if self._probabilityDensityBaseExpr is None:
      self._probabilityDensityBaseExpr = sy.sympify(self._probabilityDensity)
    expr = self._probabilityDensityBaseExpr    

    # substitute constants
    for name, val in kwargs.items():
      expr = expr.subs(name, val)

    # set variables attribute if not set
    self._variables = list(expr.free_symbols)

    # fix variable order if given
    if self._variableOrder:
      sortedVars = []
      for varName in self._variableOrder:
        varNames = [str(v) for v in self._variables]
        if varName in varNames:
          sortedVars.append(self._variables.pop(varNames.index(varName)))
      self._variables = sortedVars + self._variables

    # substitute remaining free symbols with symbols that 
    # have 'real' assumption
    _newVariables = []
    for i, sym in enumerate(self._variables):
      l1, l2 = self._variableDomains.get(str(sym), (-inf, inf))
      realSym = sy.Symbol(str(sym), real=True, 
                          **(dict(nonnegative=True) if l1>=0
                        else dict(nonpositive=True) if l2<=0
                        else {}))
      expr = expr.subs(sym, realSym)
      _newVariables.append(realSym)
    self._variables = _newVariables

    # append variables that appear in domains but not in expression
    varNames = [str(v) for v in self._variables]
    for symName in self._variableDomains.keys():
      if symName not in varNames:
        self._variables.append(sy.Symbol(symName, real=True))

    # save resulting expr in attribute
    self._probabilityDensityExpr = expr


  def _generateAnalyticScalarLambda(self, varI):
    '''
    for lambda for variable number varI integrate over full domain 
    for all var<varI and leave open any var>varI 
    '''
    # prepare symbols and domains
    expr = self._probabilityDensityExpr

    try:
      # start alarm that raises exception in this thread after timeout
      _setAlarm(self._deadline)

      # test whether expression looks positive
      isPositive = False
      try:
        if not bool( expr < 0 ):
          isPositive = True
      except Exception:
        pass
      if not isPositive:
        try:
          if not bool( sy.solve(expr < 0) ):
            isPositive = True
        except Exception:
          pass
      if not isPositive:
        io.warn(f'not sure whether expression for probability density '
                f'"{expr}" always yields positive values; negative '
                f'probabilities will lead to undefined behavior')

      # integrate along domain for i<varI
      for i in range(varI):
        var = self._variables[i]
        l1, l2 = self._variableDomains.get(str(var), (-inf, inf))
        expr = sy.Integral(expr, (var,l1,l2)).doit()

      # integrate and invert for requested var
      var = self._variables[varI]
      l1, l2 = self._variableDomains.get(str(var), (-inf, inf))

      varX = sy.Symbol('x', real=True, **(dict(positive=True) if l1>=0
                                    else dict(negative=True) if l2<=0
                                    else {}))
      varY = sy.Symbol('y', real=True, nonnegative=True)

      # find total and 
      totalIntegral = sy.Integral(expr, (var,l1,l2)).doit()
      partialIntegral = sy.Integral(expr, (var,l1,varX)).doit()
      
      exprYs = sy.solve(sy.Eq(partialIntegral/totalIntegral, varY), varX, 
                        simplify=False)  # do not simplify, this speeds up the solver a lot
      if len(exprYs) == 0:
        raise ValueError(f'expression {partialIntegral/totalIntegral} seems not to be solvable for {varX}')
      lambYs = [sy.lambdify([varY]+self._variables[varI+1:], exprY, 
                            modules=['numpy', 'scipy'])
                                            for exprY in exprYs]

      # attach expressions to lambda for convenience
      for lam in lambYs:
        lam._origExpressions = (expr/totalIntegral, partialIntegral/totalIntegral, exprYs)

    # re-raise special KeyboardInterrupt raised by timer handler as a RuntimeError,
    # re-raise any other KeyboardInterrupts unchanged
    except KeyboardInterrupt as e:
      if str(e) == 'time is up':
        raise RuntimeError('time is up')
      raise

    finally:
      # disable alarm again
      _clearAlarm()

    return lambYs

  
  def _numericalResolution(self, var):
    # set numerical resolution dict
    if not self._numericalResolutions:
      self._numericalResolutions = 5+int(1e6**(1/len(self._variables)))
    if not type(self._numericalResolutions) is dict:
      self._numericalResolutions = {str(v): self._numericalResolutions for v in self._variables}

    # get numerical resolution and ensure to return odd number
    res = int(round(self._numericalResolutions.get(str(var))))
    if res % 2 == 0:
      return res+1
    return res


  def _generateNumericScalarLambda(self, varI):
    # prepare symbols and domains
    expr = self._probabilityDensityExpr

    # make sure free symbols exactly match variable list
    for s in expr.free_symbols:
      if s not in self._variables:
        raise ValueError(f'probabilty density expression {expr} has free '
                         f'symbol {s} which is not in list of '
                         f'variables {self._variables}')

    # prepare param grid for probability density evaluation
    # additional prepare in-between ranges with values sitting between the
    # original range for use with cumsum later 
    variableRanges = []
    variableRangesInBetween = []
    for var in self._variables:
      l1, l2 = self._variableDomains.get(str(var), (-inf, inf))
      if not isfinite(l1) or not isfinite(l2):
        raise ValueError(f'failed to find analytical solution, numerical '
                         f'solution requires finite limits, but found limits '
                         f'[{l1}, {l2}] for variable {var}')
      _range = linspace(l1, l2, self._numericalResolution(var))
      variableRanges.append(_range)
      variableRangesInBetween.append((_range[1:]+_range[:-1])/2)
    variableGrids = meshgrid(*variableRangesInBetween)

    # evaluate expression
    exprLam = sy.lambdify(self._variables, expr)
    gridProbs = exprLam(*variableGrids)

    # if gridProbs is scalar replace it with array of same shape as variable grid
    if not hasattr(gridProbs, 'shape'):
      gridProbs = variableGrids[0] * 0 + gridProbs

    # check whether probabilities are strictly positive
    if (gridProbs < 0).any():
      raise ValueError(f'found negative probability density, '
                       f'expression: {expr}, variable: {self._variables[varI]}')

    # warn if neighboring points in gridsProbs differ by more than threshold
    for dim in range(len(gridProbs.shape)):
      scale = gridProbs.max()-gridProbs.min()
      if scale < 1e-10:
        scale = 1
      r1, r2 = arange(gridProbs.shape[dim])[:-1], arange(gridProbs.shape[dim])[1:]
      diff = take(gridProbs, r1, axis=dim) - take(gridProbs, r2, axis=dim)
      if abs(diff).max()/scale > self._warnIfDiscretizationStepAbove:
        io.warn(f'numerical evaluation of probability density expression '
                f'{self._probabilityDensityExpr} had jumps larger than '
                f'{1e2*self._warnIfDiscretizationStepAbove:.1f}%')

    # numerically integrate (actually just sum because normalization 
    # happens later anyways) along domain for i<varI
    for _ in range(varI):
      gridProbs = gridProbs.sum(axis=-1)

    # integrate (again actually sum) but insert zeros before to properly start from zero
    # using the in-between grid makes the result an accurate estimate for probability density
    # at a given point in the regular (not-in-between) variable grid
    gridProbs = insert(gridProbs, 0, zeros(gridProbs.shape[:-1]), axis=-1)
    gridProbs = cumsum(gridProbs, axis=-1)

    #print('-=--', varI)
    #print(gridProbs/gridProbs[...,-1].max(), variableRanges[varI])

    # make interpolator function that implements numerical inversion of the integral
    def interpolateResult(x, *params,
                          variableRanges=variableRanges,
                          variableRangesInBetween=variableRangesInBetween,
                          gridProbs=gridProbs, varI=varI):

      # loop over all draw params and assemble result array
      # if params list is empty, just run loop once with empty list as _params
      result = []
      for randIter, _params in enumerate(array(params).T if len(params) else [[]]):
        # make sure iterating over _params is possible
        if not hasattr(_params, '__len__'):
          _params = [_params]

        # if finite number of params is given, also iterate over individual x
        # if not params are given, keep shape of x to boost calculation via numpy broadcasting
        if hasattr(x, '__len__') and len(_params):
          _x = x[randIter]
        else:
          _x = x

        # select columns according to conditional variable values
        index = []
        for i, _param in enumerate(_params):
          index.append(argmin(abs(variableRangesInBetween[varI+i+1]-_param)))
        #print(f'{shape(gridProbs)=}, {index=}')
        _gridProbsCol = gridProbs[*index,:]

        # normalize to maximum entry
        _gridProbsCol /= _gridProbsCol[-1]

        # append interpolated values to result
        #print(f'{shape(_gridProbsCol)=}, {shape(variableRanges[varI])=}')
        result.append( interp(_x, _gridProbsCol, variableRanges[varI]) )

      #print(f'{shape(x)=}, {shape(params)=}, {shape(result)=}')

      # transpose results to return in same shape as params were given
      if len(params):
        #print('return array')
        return array(result).T

      # if no params were given return first result only (because there is only one in this case)
      #print('return first')
      return result[0]

    # numerically invert using interpolator
    lambYs = [interpolateResult]
    # attach placeholders instead of expressions to lambda
    for lam in lambYs:
      lam._origExpressions = ('n.a.', 'n.a.', ['n.a.'])

    return lambYs


  def draw(self, N=None, constants=None):
    '''
    Draw random numbers (or vectors) following the distribution represented by this object.

    Arguments:
    ==========
    N : int
      number of random numbers (vectors) to draw. If this argument is not passed, the return
      value will have the same shape as the random number variable implied by the distribution.
      If N is passed, the result will have an additional dimension of size N.

    constants : dict    
      Dictionary of constants to substitute in the distribution expression.
    '''

    # compile variable first if either constants are passed or
    # if it was not yet compiled
    if not hasattr(self, '_transformLambdas') or (constants is not None and constants != self._constantsDict):
      self.compile(**(constants or {}))

    # accept float values for N and limit to min 1
    if N is not None:
      N = max([1, int(round(N))])

    result = []
    for i, transforms in reversed(list(enumerate(self._transformLambdas))):
      #print(f'drawing var {self._variables[i]}...')
      l1, l2 = self._variableDomains.get(str(self._variables[i]), (-inf, inf))

      # roll standard uniform [0,1) rng and transform result, use numpy broadcasting
      # for improved performance
      rand = random.random_sample(**({} if N is None else dict(size=N)))
      #print(f'{shape(result)=}')
      vals = array([transform(rand, *result[::-1]) for transform in transforms])

      # make sure shapes match (only needed for debugging)
      if shape(vals) != (1,1) and shape(vals) != shape([rand]*len(transforms)):
        raise ValueError(f'shape mismatch {shape(vals)=} != {shape([rand]*len(transforms))=}, do '
                         f'all arguments/attributes of this object have intended shapes?')

      # find indices of resulting values that are within bounds
      valid = argwhere(logical_and(l1 <= vals, vals <= l2))

      # make sure each of the N rolls had exactly one valid result
      if any(valid[:,-1] != arange(valid.shape[0])):
        raise ValueError('no/more than one valid value found in domain')

      # append valid results to list
      if N is not None:
        result.append(vals[tuple(valid.T)])
      else:
        result.append(vals[tuple(valid.T)][0])
    
    # reverse result ordering to restore correct variable order
    result = array(result[::-1])

    # return results as dictionary with variable names as keys
    if self._variableOrder is None:
      return {str(k): v for k, v in zip(self._variables, result)}

    # if variable order is specified, return as array with first dimension ordered as given
    # first make sure variableOrdering has 1:1 match with _variables
    _varNames = [str(v) for v in self._variables]
    for v in self._variableOrder:
      if v not in _varNames:
        raise ValueError(f'variable {v} is given in variable ordering, but does not seem to '
                         f'exist in expression {self._probabilityDensityExpr}')
      _varNames.remove(v)
    if len(_varNames):
      raise ValueError(f'variables {_varNames} exist in expression {self._probabilityDensityExpr}'
                       f' but do not exist in {self._variableOrder}; are all constants specified?')

    # construct ordering index and return
    _orderingIndex = [[str(v) for v in self._variables].index(_v) for _v in self._variableOrder]
    return result[_orderingIndex]

  def drawPseudo(self, N, bins=None, overdrawFactor=0.1, overdrawIterations=50, constants=None, plotHistograms=False):
    '''
    Draw pseudo random (or vectors) almost following the distribution represented by this object.
    The histogram if the returned numbers will be close to the expected histogram, outliers are
    removed.

    Arguments:
    ==========
    N : int
      Number of random numbers (vectors) to draw. This must be greater than 1, because a histogram
      is not well defined otherwise.

    bins : int or list
      Optionally pass number of bins to consider

    constants : dict    
      Dictionary of constants to substitute in the distribution expression.

    overdrawFactor : float
      Draw N*overdrawFactor true random numbers and return only the N numbers out of these, that
      represent the expected histogram best.

    overdrawIterations : int
      Redraw new values overdrawIterations times to refine histogram 
    '''
    if N <= 1:
      raise ValueError(f'N must be greater than one in pseudo random mode')
    if overdrawFactor <= 0:
      raise ValueError(f'overdrawFactor must be greater than zero')
    if overdrawIterations <= 1:
      raise ValueError(f'overdrawIterations must be greater than one')
    if not self._variableOrder:
      raise ValueError(f'variableOrder must be passed to constructor to use pseudo random mode.')

    draws = None
    for _ in range(round(int(overdrawIterations))):
      # draw true random samples
      newDraws =  self.draw(N=round(N*overdrawFactor), constants=constants)
      if draws is None:
        # draw (1+factor)*N in the beginning instead of factor*N
        draws = self.draw(N=round(N*(1+overdrawFactor)), constants=constants)
      elif len(draws.shape) == 1:
        # concatenate with old non-nan samples
        draws = concatenate([draws[logical_not(isnan(draws))], newDraws])
      else:
        # concatenate with old non-nan samples
        draws = concatenate([draws[...,logical_not(isnan(draws[0]))], newDraws], axis=-1)

      # calc n-D histogram
      if bins is None:
        bins = int( (overdrawFactor*sqrt(overdrawIterations)*N)**(1/(3*len(self._variableOrder))) )
      hist, edges = histogramdd(draws.T, bins=bins)
      binCenters = [(e[1:]+e[:-1])/2 for e in edges]

      # calc expected histogram
      expr = self._probabilityDensityExpr
      lambdExpr = sy.lambdify(list(reversed(self._variableOrder)), expr)
      expectedHist = lambdExpr(*meshgrid(*reversed(binCenters)))

      # fix shape in case of missing variables in expression
      if not hasattr(expectedHist, 'shape'):
        expectedHist = expectedHist*ones(hist.shape)

      while True:
        # drop values in bins that have more than expected values'
        histDiff = hist/hist.sum() - expectedHist/expectedHist.sum()
        outlierIndex = argwhere(histDiff == histDiff.max())[0]
        outlierEdge1 = [e[i] for e,i in zip(edges, outlierIndex)]
        outlierEdge2 = [e[i+1] for e,i in zip(edges, outlierIndex)]

        #print(outlierEdge1, outlierEdge2)
        isInBin = None
        if len(draws.shape) == 1:
          isInBin = logical_and(outlierEdge1[0] < draws, draws <= outlierEdge2[0])
        else:
          for i, (e1, e2) in enumerate(zip(outlierEdge1, outlierEdge2)):
            _isInBin = logical_and(e1 < draws[i], draws[i] <= e2)
            if isInBin is None:
              isInBin = _isInBin
            else:
              isInBin = logical_and(isInBin, _isInBin)
        drawDeleteIndices = argwhere(isInBin)
        #print(draws[...,drawDeleteIndices[0]])

        # replace random value from that bin with nan and reduce respective histogram count by one,
        # if that bin has no values left, exit loop
        if len(drawDeleteIndices) > 0:
          drawDeleteIndex = drawDeleteIndices[int(random.random()*drawDeleteIndices.shape[0])]
          draws[...,*drawDeleteIndex] = nan
          hist[*outlierIndex] -= 1
          #print(f'hist reduced at {outlierIndex=}, removed draw index [{drawDeleteIndex=}]')
        else:
          draws = draws[...,logical_not(isnan(draws if len(draws.shape)==1 else draws[0]))]
          draws = draws[...,-int(N):]
          #print('end prematurely')
          break

        # end loop if only N values left
        if len(draws.shape) == 1:
          if sum(logical_not(isnan(draws))) <= N:
            #print('end because need more samples')
            break
        else:
          if sum(logical_not(isnan(draws[-1]))) <= N:
            #print('end because need more samples')
            break

      if plotHistograms:
        histDiff = hist/hist.sum() - expectedHist/expectedHist.sum()
        import matplotlib.pyplot as plt 
        plt.figure(figsize=(5,2))
        plt.plot(hist/hist.sum())
        plt.plot(expectedHist/expectedHist.sum())
        plt.plot(histDiff)

    # clean out nans and return, make sure length is right and return
    result = draws[...,logical_not(isnan(draws if len(draws.shape)==1 else draws[0]))]
    if draws.shape[-1] / result.shape[-1] > 5:
      warnings.warn('pseudo random generation was not very successful, maybe bins '
                    'or overdraw parameters have to be tweaked...')
    return result[...,-int(round(N)):]


  def findGrid(self, N, startFrom=None, constants=None):
    '''
    Return values whose density follows the given probability density as close as possible.
    '''
    # compile variable first if either constants are passed or
    # if it was not yet compiled
    if not hasattr(self, '_transformLambdas') or (constants is not None and constants != self._constantsDict):
      self.compile(**(constants or {}))

    # perform 1D grid generation
    if len(self._variables) == 1:
      # prepare ranges and parameters      
      var = self._variables[0]
      l1, l2 = self._variableDomains.get(str(var), (-inf, inf))
      if not isfinite(l1) or not isfinite(l2):
        raise ValueError(f'variable domains must be finite for grid generation')
      varRange = linspace(l1, l2, self._numericalResolution(var))

      # calc density
      expr = self._probabilityDensityExpr
      lambdExpr = sy.lambdify(var, expr)
      density = lambdExpr(varRange)

      # fix shape in case of missing variables in expression
      if not hasattr(density, 'shape'):
        density = density*ones(varRange.shape)

      # find startFrom parameter if not given explicitly
      if startFrom is None:
        startFrom = varRange[argmax(density)]
      
      # call algorithm from points_by_density module
      result = points_by_density.generatePointsWithGivenDensity1D(
                              density=(varRange, density),
                              N=N,
                              startFrom=startFrom)

      # clip result to range and return
      return result[logical_and(min(varRange) <= result, result <= max(varRange))]
    else:
      raise RuntimeError('grid generation is not implemented for variable count greater than 1')



class ScalarRandomVariable(VectorRandomVariable):
  '''
  Scalar valued random variable. 
  '''
  def __init__(self, probabilityDensity, variableDomain, variable=None, numericalResolution=None, **kwargs):
    self._desiredVariable = variable
    if variable is None:
      variable = str(list(sy.sympify(probabilityDensity).free_symbols)[0])
    super().__init__(probabilityDensity, 
                     variableDomains={variable: variableDomain},
                     numericalResolutions={} if numericalResolution is None else {variable: numericalResolution},
                     variableOrder=[variable,],
                     **kwargs)

  def compile(self, **kwargs):
    # subfunction that raises human readable exceptions if conditions for scalar random variable are not fulfilled 
    def _checkScalarity():
      freeSymbols = sy.sympify(self._probabilityDensityExpr).free_symbols
      if ( len(freeSymbols) 
            and self._desiredVariable is not None
            and self._desiredVariable not in [str(s) for s in freeSymbols] ):
        raise ValueError(f'specified variable "{self._desiredVariable}" does not seem to appear '
                         f'in expression "{self._probabilityDensityExpr}"')

      if len(self._variables) > 1:
        raise ValueError(f'expression "{self._probabilityDensityExpr}" seems to have more than '
                        f'one free variable after substituting constants; did you pass all constants '
                        f'to .compile() or .draw()?')

    # run vector random variable's compile and reraise exceptions caused by non-scalarity as 
    # useful human readable exceptions
    try:
      super().compile(**kwargs)
    except ValueError as e:
      if 'requires finite limits' in str(e):
        _checkScalarity()
      raise
    _checkScalarity()

  def draw(self, N=None, **kwargs):
    return super().draw(N=N, **kwargs)[0]
