from .point_source import *
from .optical_group import *
from .simulation_settings import *
from .simulation_actions import *
from .common import *
from . import find

def loadAll():
  loadPointSource()
  loadGroups()
  loadSimulationSettings()
  loadSimulationActions()
