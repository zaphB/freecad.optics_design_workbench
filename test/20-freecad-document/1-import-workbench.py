__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import pytest
import os

from optics_design_workbench import jupyter_utils

# run all tests in this module with cwd set to the directory of this test
@pytest.fixture(autouse=True)
def changeTestDir(monkeypatch):
  p = os.path.dirname(__file__)
  print(f'running test in folder {p}')
  monkeypatch.chdir(p)


def test_workbenchRegistered():
  with jupyter_utils.FreecadDocument() as f:
    res = f.execInFreecadShell(r'''
        allWb = Gui.listWorkbenches().keys()
        print(f'registered workbenches: {allWb}')
    ''')
    print(res)
    assert 'OpticsDesignWorkbench' in res

def test_importWorkbenchModule():
  with jupyter_utils.FreecadDocument() as f:
    print( f.execInFreecadShell('import freecad.optics_design_workbench') )
    print( f.execInFreecadShell('print( freecad.optics_design_workbench.versionInfo() )') )
