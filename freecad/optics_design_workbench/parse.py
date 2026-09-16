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

_UNARY_OPS = {
  ast.UAdd: operator.pos,
  ast.USub: operator.neg,
}

_CONSTANTS = {
  "pi": sy.pi,
  "e": sy.E,
  "inf": sy.oo,
  "oo": sy.oo,
  "i": 1j,
  "j": 1j,
}

_FUNCTIONS = {
  "exp": sy.exp,
  "log": sy.log,
  "ln": sy.log,
  "sqrt": sy.sqrt,
  "sin": sy.sin,
  "cos": sy.cos,
  "tan": sy.tan,
  "asin": sy.asin,
  "arcsin": sy.asin,
  "acos": sy.acos,
  "arccos": sy.acos,
  "atan": sy.atan,
  "arctan": sy.atan,
  "sinh": sy.sinh,
  "cosh": sy.cosh,
  "tanh": sy.tanh,
  "Abs": sy.Abs,
  "abs": sy.Abs,
  "DiracDelta": sy.DiracDelta,
  "Heaviside": sy.Heaviside,
}


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

  # else: use AST parser to create tree and traverse tree to resolve according
  #       to global whitelists
  try:
    tree = ast.parse(expr, mode="eval")
  except SyntaxError as e:
    raise UnsafeExpressionError(f"Could not parse expression: {e}") from e

  return _convert(tree.body, allowedSymbols)


def _convert(node: ast.AST, allowedSymbols: set[str] | None) -> sy.Expr:
  '''
  Traverse tree and resolve into sympy expression
  '''
  # numeric literals: 3, 3.14, ...
  if isinstance(node, ast.Constant):
    value = node.value
    if isinstance(value, bool):
      raise UnsafeExpressionError("boolean literals are not allowed")
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
    left = _convert(node.left, allowedSymbols)
    right = _convert(node.right, allowedSymbols)
    return _BIN_OPS[op_type](left, right)

  # unary operations: -a, +a
  if isinstance(node, ast.UnaryOp):
    op_type = type(node.op)
    if op_type not in _UNARY_OPS:
      raise UnsafeExpressionError(f"disallowed unary operator: {op_type.__name__}")
    operand = _convert(node.operand, allowedSymbols)
    return _UNARY_OPS[op_type](operand)

  # function calls: exp(...), sin(...), DiracDelta(...), ...
  if isinstance(node, ast.Call):
    if not isinstance(node.func, ast.Name):
      raise UnsafeExpressionError("only plain function calls are allowed, e.g. exp(x)")
    if node.func.id not in _FUNCTIONS:
      raise UnsafeExpressionError(f"function not allowed: {node.func.id!r}")
    if node.keywords:
      raise UnsafeExpressionError("keyword arguments are not allowed")
    args = [_convert(a, allowedSymbols) for a in node.args]
    return _FUNCTIONS[node.func.id](*args)

  # everything else is explicitly rejected: Attribute, Subscript, Lambda,
  # comprehensions, BoolOp, Compare, Call with non-Name func, strings,
  # Import, ...
  raise UnsafeExpressionError(f"disallowed syntax: {type(node).__name__}")

