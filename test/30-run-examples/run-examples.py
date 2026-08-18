__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import pytest
import os
import time
import subprocess
import pathlib

from optics_design_workbench import jupyter_utils

# run all tests in this module with cwd set the examples/1-getting-started directory
@pytest.fixture(autouse=True)
def changeTestDir(monkeypatch):
  p = os.path.dirname(__file__+'/../../examples/1-getting-started')
  print(f'running test in folder {p}')
  monkeypatch.chdir(p)

# parametrized fixture yielding every notebook in the
allNotebooks = sorted(pathlib.Path(__file__).parent.rglob("*.ipynb"))
@pytest.fixture(params=allNotebooks, ids=lambda p: p.stem if hasattr(p, 'stem') else '?')
def eachNotebook(request):
  return request.param

# run the FCStd file in true simulation mode
def test_runExampleSimulation():
  with jupyter_utils.FreecadDocument() as _f:
    _f.runSimulation('true')

# run each notebook in inline style (to contribute to coverage)
# and using nbconvert to update the outputs in the notebook
def test_runPythonNotebooks(eachNotebook, runNotebook):
  print(f'inline-mode running notebook at {eachNotebook}')
  runNotebook( eachNotebook )

  print(f'nbconvert running notebook at {eachNotebook}')
  subprocess.run(f'jupyter nbconvert --to notebook --inplace --execute "{eachNotebook}"', shell=True, text=True, check=True)

