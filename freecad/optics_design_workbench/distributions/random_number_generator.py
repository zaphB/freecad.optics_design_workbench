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
  def __init__(self, probabilityDensity, variableDomains=None, numericalResolutions=None):
    self._probabilityDensity = probabilityDensity
    self._probabilityDensityBaseExpr = None
    self._variables = None
    self._variableDomains = variableDomains
    self._numericalResolutions = numericalResolutions
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
    if self._numericalResolutions is None:
      self._numericalResolutions = 5+int(1e4**(1/len(self._variables)))
    if not hasattr(self._numericalResolutions, '__iter__'):
      self._numericalResolutions = [self._numericalResolutions for _ in self._variables]

    # prepare param grid for probability density evaluation
    variableRanges = []
    #print(f'making grid with {self._numericalResolutions}')
    for i, var in enumerate(self._variables):
      l1, l2 = self._variableDomains.get(str(var), (-inf, inf))
      if not isfinite(l1) or not isfinite(l2):
        raise ValueError(f'failed to find analytical solution, numerical '
                         f'solution requires finite limits, but found limits '
                         f'[{l1}, {l2}] for variable {var}')
      variableRanges.append(linspace(l1, l2, self._numericalResolutions[i]))
    variableGrids = meshgrid(*variableRanges)

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
      gridProbs = gridProbs.sum(axis=0)

    # integrate (again actually sum)
    gridProbs = cumsum(gridProbs, axis=0)
    #print('-=--', varI)
    #print(gridProbs, variableRanges[varI])

    # make interpolator function that implements numerical inversion of the integral
    def interpolateResult(x, *params,
                          variableRanges=variableRanges,
                          gridProbs=gridProbs, varI=varI):
      # select columns according to conditional variable values
      index = []
      for i, param in enumerate(params):
        index.append(argmin(abs(variableRanges[varI+i+1]-param)))
      gridProbs = gridProbs[:,*index]

      # normalize to maximum entry
      gridProbs /= gridProbs[-1]

      return interp(x, gridProbs, variableRanges[varI])      

    # numerically invert using interpolator
    lambYs = [interpolateResult]
    # attach placeholders instead of expressions to lambda
    for lam in lambYs:
      lam._origExpressions = ('n.a.', 'n.a.', ['n.a.'])

    return lambYs


  def draw(self, N=None):
    result = []
    for i, transforms in reversed(list(enumerate(self._transformLambdas))):
      l1, l2 = self._variableDomains.get(str(self._variables[i]), (-inf, inf))

      # roll standard uniform [0,1) rng and transform result, use numpy broadcasting
      # for improved performance
      rand = random.random_sample(**({} if N is None else dict(size=N)))
      vals = array([transform(rand, *result[::-1]) for transform in transforms])

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
    return array(result[::-1])


class ScalarRandomVariable(VectorRandomVariable):
  '''
  Scalar valued random variable. 
  '''
  def __init__(self, probabilityDensity, variableDomain, numericalResolution=None, **kwargs):
    super().__init__(probabilityDensity, 
                     variableDomains=[variableDomain],
                     numericalResolutions=None if numericalResolution is None else [numericalResolution], 
                     **kwargs)

  def draw(self, **kwargs):
    return super().draw(**kwargs)[0]
