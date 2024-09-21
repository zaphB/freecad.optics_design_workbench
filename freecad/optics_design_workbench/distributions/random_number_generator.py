'''
Classes to generate random numbers according to arbitrary probability distribution functions.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import sympy as sy
import warnings
import time
import signal


def _setAlarm(deadline):
    timeout = deadline-time.time()
    if timeout < 0:
      raise RuntimeError('time is up')
    def handler(sig, n):
      raise RuntimeError('time is up')
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(int(timeout)+1)


def _clearAlarm():
  signal.alarm(0)


class VectorRandomVariable:
  '''
  Vector valued random variable. 
  '''
  def __init__(self, probabilityDensity, variableDomains={}, numericalResolutions={}, variableOrder=None):
    self._probabilityDensity = probabilityDensity
    self._probabilityDensityBaseExpr = None
    self._variables = None
    self._variableDomains = variableDomains
    self._numericalResolutions = numericalResolutions
    self._variableOrder = variableOrder
    self._mode = 'not yet compiled'


  def compile(self, timeout=5, disableAnalytical=False, **kwargs):
    self._deadline = time.time()+timeout
    self._setConstants(**kwargs)

    try:
      # immediately go to numerical fallback if analytical is disabled
      if disableAnalytical:
        raise ValueError('stop')

      # try to analytical treatment first
      self._transformLambdas = [self._generateAnalyticScalarLambda(i) for i in range(len(self._variables))]
      self._mode = 'analytic'

    except Exception:
      # fallback to numerical treatment and analytical mode did not succeed
      self._transformLambdas = [self._generateNumericScalarLambda(i) for i in range(len(self._variables))]
      self._mode = 'numeric'


  def mode(self):
    return self._mode


  def showExpressions(self, simplify=True):
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
    if self._probabilityDensityBaseExpr is None:
      self._probabilityDensityBaseExpr = sy.sympify(self._probabilityDensity)
    expr = self._probabilityDensityBaseExpr    
    
    # substitute constants
    for name, val in kwargs.items():
      expr = expr.subs(name, val)
    
    # set variables attribute if not set
    self._variables = list(expr.free_symbols)

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

      # test wether expression looks positive
      try:
        if bool(sy.solve(expr < 0)):
          raise ValueError('oops')
      except Exception:
        warnings.warn(f'not sure whether expression for probability density '
                      f'"{expr}" will always yield '
                      f'positve values, which will break the RNG')

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
      
      exprYs = sy.solve(sy.Eq(partialIntegral/totalIntegral, varY), varX)
      if len(exprYs) == 0:
        raise ValueError(f'expression {partialIntegral/totalIntegral} seems not to be solvable for {varX}')
      lambYs = [sy.lambdify([varY]+self._variables[varI+1:], exprY)
                                                for exprY in exprYs]

      # attach expressions to lambda for convenience
      for lam in lambYs:
        lam._origExpressions = (expr/totalIntegral, partialIntegral/totalIntegral, exprYs)

    finally:
      # disable alarm again
      _clearAlarm()

    return lambYs


  def _generateNumericScalarLambda(self, varI):
    # prepare symbols and domains
    expr = self._probabilityDensityExpr

    # make sure free symbols exactly match variable list
    for s in expr.free_symbols:
      if s not in self._variables:
        raise ValueError(f'probabilty density expression {expr} has free '
                         f'symbol {s} which is not in list of '
                         f'variables {self._variables}')

    # make sure resolution is list of right length
    if not self._numericalResolutions:
      self._numericalResolutions = 5+int(1e4**(1/len(self._variables)))
    if not type(self._numericalResolutions) is dict:
      self._numericalResolutions = {str(v): self._numericalResolutions for v in self._variables}

    # prepare param grid for probability density evaluation
    # additional prepare in-between ranges with values sitting between the
    # original range for use with cumsum later 
    variableRanges = []
    variableRangesInBetween = []
    #print(f'making grid with {self._numericalResolutions}')
    for var in self._variables:
      l1, l2 = self._variableDomains.get(str(var), (-inf, inf))
      if not isfinite(l1) or not isfinite(l2):
        raise ValueError(f'failed to find analytical solution, numerical '
                         f'solution requires finite limits, but found limits '
                         f'[{l1}, {l2}] for variable {var}')
      _range = linspace(l1, l2, self._numericalResolutions[str(var)])
      variableRanges.append(_range)
      variableRangesInBetween.append((_range[1:]+_range[:-1])/2)
    variableGrids = meshgrid(*variableRangesInBetween)

    # evaluate expression
    exprLam = sy.lambdify(self._variables, expr)
    gridProbs = exprLam(*variableGrids)

    # make sure no negative entries exist
    if (gridProbs < 0).any():
      raise ValueError(f'found negative probability density, '
                       f'expression: {expr}, variable: {self._variables[varI]}')

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


  def draw(self, N=None):
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
        raise ValueError(f'variable {v} is given in variable ordering, but does not seem to exist in expression {self._probabilityDensityExpr}')
      _varNames.remove(v)
    if len(_varNames):
      raise ValueError(f'variables {_varNames} exist in expression {self._probabilityDensityExpr} but do not exist in {self._variableOrder}')

    # construct ordering index and return
    _orderingIndex = [[str(v) for v in self._variables].index(_v) for _v in self._variableOrder]
    return result[_orderingIndex]


class ScalarRandomVariable(VectorRandomVariable):
  '''
  Scalar valued random variable. 
  '''
  def __init__(self, probabilityDensity, variableDomain, variable=None, numericalResolution=None, **kwargs):
    if variable is None:
      variable = str(list(sy.sympify(probabilityDensity).free_symbols)[0])
    super().__init__(probabilityDensity, 
                     variableDomains={variable: variableDomain},
                     numericalResolutions=None if numericalResolution is None else {variable: numericalResolution},
                     variableOrder=[variable,],
                     **kwargs)

  def draw(self, N=None, **kwargs):
    return super().draw(N=N, **kwargs)[0]
