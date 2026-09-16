__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

"""
The initial version of this module was mostly build by Claude Sonnet 5, thanks Claude!

Safe, AST-based replacement for sy.sympify().

sy.sympify() ultimately parses strings via an eval()-based mechanism,
which can execute arbitrary code (see zaphB/freecad.optics_design_workbench#51).
This module builds sympy expressions directly from the Python AST
(ast.parse(..., mode="eval")) instead. eval()/exec() are never called,
and only explicitly whitelisted node types, operators, constants and
functions are accepted - everything else (attribute access, subscripting,
comprehensions, lambdas, calls to unknown names, ...) is rejected with a
clear error instead of being silently executed.

Limitation compared to real sympify(): implicit multiplication like "2x"
is NOT supported, because that is not valid Python syntax. Write "2*x"
instead.
"""

import ast
import operator

import sympy as sy
import numpy as np


class UnsafeExpressionError(ValueError):
  """Raised when the expression contains disallowed syntax."""


# ---------------------------------------------------------------------------
# Whitelists: only what is listed here is accepted
# ---------------------------------------------------------------------------

_BIN_OPS = {
  ast.Add: operator.add,
  ast.Sub: operator.sub,
  ast.Mult: operator.mul,
  ast.Div: operator.truediv,
  ast.Pow: operator.pow,
  ast.Mod: operator.mod,
}

_BOOL_OPS = {
  ast.And: operator.and_,
  ast.Or: operator.or_,
}  

_COMP_OPS = {
  ast.Eq: operator.eq,
  ast.NotEq: operator.ne,
  ast.Lt: operator.lt,
  ast.LtE: operator.le,
  ast.Gt: operator.gt,
  ast.GtE: operator.ge,
  ast.Is: operator.is_,
  ast.IsNot: operator.is_not,
}

_UNARY_OPS = {
  ast.UAdd: operator.pos,
  ast.USub: operator.neg,
  ast.Not: operator.not_,
}

_CONSTANTS = {
  'pi': sy.pi,
  'e': sy.E,
  'inf': sy.oo,
  'oo': sy.oo,
  'i': 1j,
  'j': 1j,
}

_FUNCTIONS = {
  'exp': sy.exp,
  'log': sy.log,
  'ln': sy.log,
  'sqrt': sy.sqrt,
  'sin': sy.sin,
  'cos': sy.cos,
  'tan': sy.tan,
  'asin': sy.asin,
  'arcsin': sy.asin,
  'acos': sy.acos,
  'arccos': sy.acos,
  'atan': sy.atan,
  'arctan': sy.atan,
  'sinh': sy.sinh,
  'cosh': sy.cosh,
  'tanh': sy.tanh,
  'Abs': sy.Abs,
  'abs': sy.Abs,
  'DiracDelta': sy.DiracDelta,
  'Heaviside': sy.Heaviside,
  'Piecewise': sy.Piecewise,
  'Vector': np.array,
  'Matrix': np.array,
}

def listOfStrings(expr: str):
  '''
  Parse `expr` into a list of strings, using only Python's built-in `ast` module -
  no eval()/exec(), no sympy.sympify().

  Parameters
  ----------

  expr : str
    String or expression representing a list of strings.

  Returns
  -------

  list[str]
    Parsed list of strings.
  '''
  try:
    tree = ast.parse(expr, mode="eval")
  except SyntaxError as e:
    raise UnsafeExpressionError(f"Could not parse expression: {e}") from e
  res = _convert(tree.body, allowStrings=True)
  if (type(res) is not list 
        or not all([ type(e) is str for e in res ]) ):
    raise UnsafeExpressionError(f'parsing expression did not yield expected list of strings: {expr!r}')
  return res


def constantValue(expr):
  '''
  Parse `expr` into a constant number, using only Python's built-in `ast` module -
  no eval()/exec(), no sympy.sympify().

  Parameters
  ----------

  expr : str
    String or expression representing a constant value.

  Returns
  -------

  any
    Parsed value.
  '''
  try:
    tree = ast.parse(expr, mode="eval")
  except SyntaxError as e:
    raise UnsafeExpressionError(f"Could not parse expression: {e}") from e
  return _convert(tree.body, allowedSymbols=[], allowStrings=True)


def constantNumber(expr: str|sy.Expr):
  '''
  Parse `expr` into a constant number, using only Python's built-in `ast` module -
  no eval()/exec(), no sympy.sympify().

  Parameters
  ----------

  expr : str | sy.Expr
    String or expression representing a constant number.

  Returns
  -------

  float | complex
    Parsed number.
  '''
  # first try to directly convert to number
  try:
    return float(expr)
  except Exception:
    try:
      return complex(expr)
    except Exception:
      pass

  # use sympy parser and try to eval to float
  num = sympyExpression(expr).evalf()
  try:
    return float(num)
  except Exception:
    return complex(num)


def sympyExpression(expr: str|sy.Expr, allowedSymbols: set[str] | None = None) -> sy.Expr:
  """
  Parse `expr` into a sympy expression, using only Python's built-in `ast` module -
  no eval()/exec(), no sympy.sympify().


  Parameters
  ----------

  expr : str | sy.Expr
    String or expression to parse.

  allowedSymbols : set[str], optional
    If given, only these names may appear as free variables (e.g. {"theta", "x"}). 
    Pass None to allow any identifier as a symbol.

  Returns
  -------

  float | complex
    Parsed number.
  """
  # in case expr is already a sympy expression, just check free_symbols
  # are in allowlist and return
  if isinstance(expr, sy.Expr):
    if allowedSymbols is not None:
      for sym in expr.free_symbols:
        if str(sym) not in allowedSymbols:
          raise UnsafeExpressionError(f"symbol not allowed: {sym!r}")
    return expr

  # strip whitespaces to avoid 'unexpected indent' errors
  expr = expr.strip()

  # string replace ^ to ** to support ^ as power operator with same operator
  # priority as **. Only drawback: we have to forbid strings in our expression, 
  # because the simple replacement below would not only replace the operators
  # but also string values
  expr = expr.replace('^', '**')

  # use AST parser to create tree and traverse tree to resolve according
  # to global whitelists
  try:
    tree = ast.parse(expr, mode="eval")
  except SyntaxError as e:
    raise UnsafeExpressionError(f"Could not parse expression: {e}") from e

  return _convert(tree.body, allowedSymbols, allowStrings=False)


def _convert(node: ast.AST, allowedSymbols: set[str] | None=None, allowStrings=False) -> sy.Expr:
  '''
  Traverse tree and resolve into python/sympy expression
  '''
  kwargs = dict(allowedSymbols=allowedSymbols, allowStrings=allowStrings)

  # numeric literals: 3, 3.14, ...
  if isinstance(node, ast.Constant):
    value = node.value
    if isinstance(value, str) or isinstance(value, np.str_):
      if allowStrings:
        return str(value)
      else:
        raise UnsafeExpressionError("string literals are not allowed")
    if isinstance(value, bool):
      return bool(value)
    if isinstance(value, int):
      return sy.Integer(value)
    if isinstance(value, float):
      return sy.Float(value)
    if isinstance(value, complex):
      return complex(value)
    raise UnsafeExpressionError(f"disallowed literal type: {type(value).__name__}")

  # names: known constants (pi, e, inf) or free variables
  if isinstance(node, ast.Name):
    if node.id in _CONSTANTS:
      return _CONSTANTS[node.id]
    if allowedSymbols is not None and node.id not in allowedSymbols:
      raise UnsafeExpressionError(f"symbol not allowed: {node.id!r}")
    return sy.Symbol(node.id)

  # binary operations: a + b, a * b, a ** b, ...
  if isinstance(node, ast.BinOp):
    op_type = type(node.op)
    if op_type not in _BIN_OPS:
      raise UnsafeExpressionError(f"disallowed operator: {op_type.__name__}")
    left = _convert(node.left, **kwargs)
    right = _convert(node.right, **kwargs)
    return _BIN_OPS[op_type](left, right)

  # boolean operations: a and b, a or b
  if isinstance(node, ast.BoolOp):
    opType = type(node.op)
    if opType not in _BOOL_OPS:
      raise UnsafeExpressionError(f"disallowed operator: {opType.__name__}")
    res = None
    values = [_convert(v, **kwargs) for v in node.values]
    for v1, v2 in zip(values[:-1], values[1:]):
      if res is None:
        res = _BOOL_OPS[opType](v1, v2)
      else:
        res = _BOOL_OPS[opType](res, v2)
    return res

  # comparisons: a < b, a != b, a >= b, ...
  if isinstance(node, ast.Compare):
    left = _convert(node.left, **kwargs)
    result = True
    for op, right in zip(node.ops, node.comparators):
      if type(op) not in _COMP_OPS:
        raise UnsafeExpressionError(f"disallowed operator: {opType.__name__}")
      right = _convert(right, **kwargs)
      result = result and _COMP_OPS[type(op)](left, right)
      left = right
    return result

  # unary operations: -a, +a
  if isinstance(node, ast.UnaryOp):
    op_type = type(node.op)
    if op_type not in _UNARY_OPS:
      raise UnsafeExpressionError(f"disallowed unary operator: {op_type.__name__}")
    operand = _convert(node.operand, **kwargs)
    return _UNARY_OPS[op_type](operand)

  # function calls: exp(...), sin(...), DiracDelta(...), ...
  if isinstance(node, ast.Call):
    if not isinstance(node.func, ast.Name):
      raise UnsafeExpressionError("only plain function calls are allowed, e.g. exp(x)")
    if node.func.id not in _FUNCTIONS:
      raise UnsafeExpressionError(f"function not allowed: {node.func.id!r}")
    if node.keywords:
      raise UnsafeExpressionError("keyword arguments are not allowed")
    args = [_convert(a, **kwargs) for a in node.args]
    res = _FUNCTIONS[node.func.id](*args)
    try: 
      # convert any numpy array to float if possible
      res = res.astype('float')
    except Exception:
      pass
    return res

  # recursively handle lists if allowed
  if (isinstance(node, ast.List) or isinstance(node, ast.Tuple)):
    return [_convert(e, **kwargs) for e in node.elts]

  # everything else is explicitly rejected: Attribute, Subscript, Lambda,
  # comprehensions, BoolOp, Compare, Call with non-Name func, strings,
  # Import, ...
  raise UnsafeExpressionError(f"disallowed syntax: {type(node).__name__}")
