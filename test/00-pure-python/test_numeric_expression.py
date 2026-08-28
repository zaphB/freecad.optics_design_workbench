__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2026  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

import math
import pathlib
import sys

import pytest


sys.path.insert(0, str(pathlib.Path(__file__).parents[2]
                                  / 'freecad'
                                  / 'optics_design_workbench'
                                  / 'freecad_elements'))

from numeric_expression import parseNumericExpression


@pytest.mark.parametrize(('expression', 'expected'), [
  ('0', 0),
  ('0.07*pi', 0.07*math.pi),
  ('-pi/2 + 1e-3', -math.pi/2 + 1e-3),
  ('inf', math.inf),
])
def test_parses_numeric_expressions_used_by_freecad_documents(expression, expected):
  assert parseNumericExpression(expression) == pytest.approx(expected)


def test_rejects_code_execution(tmp_path):
  target = tmp_path / 'executed'

  with pytest.raises(ValueError):
    parseNumericExpression(
      f'__import__("pathlib").Path("{target}").write_text("executed")')

  assert not target.exists()
