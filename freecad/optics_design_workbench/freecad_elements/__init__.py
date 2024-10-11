'''
Definitions for behavior/objects/commands living in the FreeCAD projects. The ray-tracing code is in here, because it is inherently connected to the FreeCAD geometry engine.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from .point_source import *
from .replay_source import *
from .optical_group import *
from .simulation_settings import *
from .simulation_actions import *
from .common import *
from . import find

def loadAll():
  '''
  Load all FreeCAD components defined in the submodules and add them to the interface.
  '''
  loadPointSource()
  loadReplaySource()
  loadGroups()
  loadSimulationSettings()
  loadSimulationActions()
