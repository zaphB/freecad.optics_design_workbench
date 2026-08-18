__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

import pytest
import time
import subprocess
import os
import pathlib

allNotebooks = sorted(pathlib.Path(__file__).parent.rglob("*.ipynb"))
@pytest.fixture(params=allNotebooks, ids=lambda p: p.stem if hasattr(p, 'stem') else '?')
def eachNotebook(request):
  return request.param

def test_runPythonNotebooks(eachNotebook, runNotebook):
  print(f'running notebook at {eachNotebook}')
  runNotebook( eachNotebook )
