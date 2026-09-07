__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2026  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

import ast
import math
import operator


_CONSTANTS = {
  'e': math.e,
  'inf': math.inf,
  'pi': math.pi,
}

_BINARY_OPERATORS = {
  ast.Add: operator.add,
  ast.Sub: operator.sub,
  ast.Mult: operator.mul,
  ast.Div: operator.truediv,
  ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
  ast.UAdd: operator.pos,
  ast.USub: operator.neg,
}


def parseNumericExpression(expression):
  '''Parse a scalar numeric expression without executing arbitrary code.'''
  if not isinstance(expression, str):
    raise ValueError('numeric expression must be a string')
  if len(expression) > 256:
    raise ValueError('numeric expression is too long')

  try:
    parsed = ast.parse(expression, mode='eval')
  except SyntaxError as exc:
    raise ValueError(f'invalid numeric expression: {expression!r}') from exc

  if sum(1 for _ in ast.walk(parsed)) > 64:
    raise ValueError('numeric expression is too complex')

  return float(_evaluateNode(parsed.body))


def _evaluateNode(node):
  if isinstance(node, ast.Constant):
    if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
      raise ValueError('numeric expression contains a non-numeric literal')
    return float(node.value)

  if isinstance(node, ast.Name) and node.id in _CONSTANTS:
    return _CONSTANTS[node.id]

  if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
    operation = _BINARY_OPERATORS[type(node.op)]
    return operation(_evaluateNode(node.left), _evaluateNode(node.right))

  if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
    operation = _UNARY_OPERATORS[type(node.op)]
    return operation(_evaluateNode(node.operand))

  raise ValueError(f'unsupported numeric expression element: {node.__class__.__name__}')
