__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import pytest
import os

from optics_design_workbench import jupyter_utils

baseDir = os.path.abspath(os.path.dirname(__file__))

@pytest.mark.long
def test_surfaceSourceRuns():
  
  # open GUI for debugging if needed
  #jupyter_utils.openFreecadGui(f'{baseDir}/imported-stepfile-as-surface-source.FCStd')

  with jupyter_utils.FreecadDocument(f'{baseDir}/imported-stepfile-as-surface-source.FCStd') as f:
    f.runSimulation('fans')
    f.runSimulation('true')
  