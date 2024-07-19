__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

'''.strip()


try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

import os
import warnings

from . import point_source
from . import optical_group
from . import simulation_settings

def iconpath(name):
  return os.path.join(os.path.dirname(__file__), '../icons', name+'.svg')


def _allObjects():
  return App.activeDocument().Objects


def lightSources():
  '''
  yield all light source objects in the current project.
  '''
  for obj in _allObjects():
    if ( obj.TypeId == 'Part::FeaturePython'
            and isinstance(obj.Proxy, point_source.PointSourceProxy) ):
      yield obj


def relevantOpticalObjects(lightSource=None):
  '''
  yield all optical objects in project
  '''
  ignoreList = []
  if lightSource:
    ignoreList = lightSource.IgnoredOpticalElements
  for group in App.activeDocument().Objects:
    if ( group.TypeId == 'App::LinkGroupPython'
          and isinstance(group.Proxy, optical_group.OpticalGroupProxy)
          and group not in ignoreList):
      yield group


def simulationSettings():
  '''
  yield all simulation object of the current project.
  '''
  for obj in _allObjects():
    if ( obj.TypeId == 'Part::FeaturePython'
            and isinstance(obj.Proxy, simulation_settings.SimulationSettingsProxy) ):
      yield obj


def activeSimulationSettings(default=None):
  '''
  Return active simulation object of the current project or None if no 
  active simulation settings object exists.
  '''
  active = []
  allSettings = []
  for obj in simulationSettings():
    allSettings.append(obj)
    if obj.Active:
      active.append(obj)
  if len(active) > 1:
    raise ValueError('only one simulation settings object may have its "Active" property '
                     'set to true, but the following objects are active: '
                     +', '.join([obj.Name for obj in active]))
  if len(active) == 1:
    return active[0]

  # if settings exist but for some reason not a single one is active, 
  # make the first one active
  if len(allSettings):
    if default is None:
      default = allSettings[0]
    warnings.warn(f'found simulation settings objects but none of them seems to '
                  f'be active, defaulting to {default.Name}')
    return default
