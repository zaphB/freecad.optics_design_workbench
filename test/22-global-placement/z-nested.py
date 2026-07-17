__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import pytest
import os

from optics_design_workbench import jupyter_utils

baseDir = os.path.abspath(os.path.dirname(__file__))

def test_deeplyNestedProjectWorks():
  
  # open GUI for debugging if needed
  #jupyter_utils.openFreecadGui(f'{baseDir}/main.FCStd')

  with jupyter_utils.FreecadDocument(f'{baseDir}/nested-structure.FCStd') as f:
    r = f.runSimulation('true')
    print(f'{len(r.loadHits('*'))} rays hit the absorber')
    assert len(r.loadHits('*')) > 90
