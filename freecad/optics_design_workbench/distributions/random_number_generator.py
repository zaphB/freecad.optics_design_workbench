'''
Classes to generate random numbers according to arbitrary probability distribution functions.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

import random
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


  def compile(self, timeout=30, **kwargs):
    self._setConstants(**kwargs)
    self._transformLambdas = [self._generateScalarLambda(i) for i in range(len(self._variables))]


  def _setConstants(self, **kwargs):
    expr = sy.sympify(self._probabilityDensity)
    # substitute constants
    for name, val in kwargs.items():
      expr = expr.subs(name, val)
    
    # save resulting expr in attribute
    self._probabilityDensityExpr = expr
    if self._variables is None:
      self._variables = expr.free_symbols


  def _generateScalarLambda(self, varI):
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
    
    print(sy.solve(sy.Eq(partialIntegral/totalIntegral, varY), varX))
    exprYs = sy.solve(sy.Eq(partialIntegral/totalIntegral, varY), varX)
    lambYs = [sy.lambdify([varY]+self._variables[varI+1:], exprY)
                                              for exprY in exprYs]
    return lambYs


  def draw(self):
    result = []
    for i, transforms in reversed(list(enumerate(self._transformLambdas))):
      l1, l2 = self._variableDomains[i]
      rand = random.random()
      vals = [transform(rand, *result[::-1]) for transform in transforms]
      vals = [val for val in vals if l1 <= val and val <= l2]
      if len(vals) == 0:
        raise ValueError('no value found in domain')
      elif len(vals) > 1:
        raise ValueError('more than one value found in domain')
      result.append(vals[0])
    return result[::-1]



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