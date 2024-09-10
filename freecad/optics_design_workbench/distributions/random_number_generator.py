'''
Classes to generate random numbers according to arbitrary probability distribution functions.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import sympy as sy


class VectorRandomVariable:
  '''
  Vector valued random variable. 
  '''
  def __init__(self, probabilityDensity, variables, numericalResolutions, variableDomains):
    self._probabilityDensity = probabilityDensity
    self._variables = variables
    self._numericalResolutions = numericalResolutions
    self._variableDomains = variableDomains
    self._mode = 'not yet compiled'


  def compile(self, timeout=30, **kwargs):
    self._setConstants(**kwargs)
    try:
      self._transformLambdas = [self._generateAnalyticScalarLambda(i) for i in range(len(self._variables))]
      self._mode = 'analytic'
    except ValueError:
      self._transformLambdas = [self._generateNumericScalarLambda(i) for i in range(len(self._variables))]
      self._mode = 'numeric'


  def mode(self):
    return self._mode


  def showExpressions(self, simplify=True):
    print('probability density expression: ', self._probabilityDensityExpr, ' variables: ', self._variables)
    for i, var in enumerate(self._variables):
      print(f'variable "{var}" '+('conditional' if i<len(self._variables)-1 else '')+f' probability density: ')
      probDens, integral, invertedSols = self._transformLambdas[i][0]._origExpressions
      if simplify:
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
    expr = sy.sympify(self._probabilityDensity)
    # substitute constants
    for name, val in kwargs.items():
      expr = expr.subs(name, val)
    
    # save resulting expr in attribute
    self._probabilityDensityExpr = expr
    if self._variables is None:
      self._variables = expr.free_symbols


  def _generateAnalyticScalarLambda(self, varI):
    '''
    for lambda for variable number varI integrate over full domain 
    for all var<varI and leave open any var>varI 
    '''
    # prepare symbols and domains
    expr = self._probabilityDensityExpr

    # integrate along domain for i<varI
    for i in range(varI):
      var = self._variables[i]
      l1, l2 = self._variableDomains[i]
      expr = sy.Integral(expr, (var,l1,l2)).doit()

    # integrate and invert for requested var
    var = self._variables[varI]
    l1, l2 = self._variableDomains[varI]
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

    return lambYs


  def _generateNumericScalarLambda(self, varI):
    raise ValueError('not implemented')


  def draw(self, N=None):
    result = []
    for i, transforms in reversed(list(enumerate(self._transformLambdas))):
      l1, l2 = self._variableDomains[i]

      # roll standard uniform [0,1) rng and transform result, use numpy broadcasting
      # for improved performance
      rand = random.random_sample(**({} if N is None else dict(size=N)))
      vals = array([transform(rand, *result[::-1]) for transform in transforms])

      # find indices of resulting values that are within bounds
      valid = argwhere(logical_and(l1 <= vals, vals <= l2))

      # make sure each of the N rolls had exactly one valid result
      if any(valid[:,1] != arange(valid.shape[0])):
        raise ValueError('no/more than one valid value found in domain')

      # append result vector to list
      print(vals, valid)
      result.append(take(vals, valid))
    return array(result[::-1])



class ScalarRandomVariable(VectorRandomVariable):
  '''
  Scalar valued random variable. 
  '''
  def __init__(self, probabilityDensity, numericalResolution, variableDomain, **kwargs):
    super().__init__(probabilityDensity, 
                     variables=None, 
                     numericalResolutions=[numericalResolution], 
                     variableDomains=[variableDomain],
                     **kwargs)

  def draw(self, **kwargs):
    return super().draw(**kwargs)[0]
