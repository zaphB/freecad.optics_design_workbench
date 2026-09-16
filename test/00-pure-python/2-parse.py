__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2026  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

import math
import numpy as np
import sympy as sy
import pathlib
import sys

import pytest

from optics_design_workbench import parse

@pytest.mark.parametrize(('expression', 'expected'), [
  ('0', 0),
  ('0.07*pi', 0.07*math.pi),
  ('-pi/2 + 1e-3', -math.pi/2 + 1e-3),
  ('inf', math.inf),
  ('inf', np.inf),
])
def test_parses_constant_number_expressions(expression, expected):
  assert parse.constantNumber(expression) == pytest.approx(expected)


@pytest.mark.parametrize('expression', [
  'x**2',
])
def test_parses_sympy_expressions(expression):
  expr = parse.sympyExpression(expression, allowedSymbols=['x'])
  X = np.linspace(0, 1, 50)
  vals = sy.lambdify('x', expr)(X)
  expectVals = sy.lambdify('x', sy.sympify(expression))(X)
  assert all([np.isclose(x, _x) for x, _x in zip(vals, expectVals)])


def test_obeys_allowed_symbols_list():
  parse.sympyExpression('2*x + y**2', allowedSymbols=['x', 'y'])
  with pytest.raises(ValueError):
    parse.sympyExpression('2*x + y**2 + z', allowedSymbols=['x', 'y'])


def test_rejects_code_execution(tmp_path):
  target = tmp_path / 'executed'

  with pytest.raises(ValueError):
    parse.constantNumber(
      f'__import__("pathlib").Path("{target}").write_text("executed")')

  assert not target.exists()
