__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


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
  # this hast to be imported here to avoid circular import problems
  from .. import simulation

  for obj in simulation.simulatingDocument().Objects:
    # make sure TypeId attribute can be read without exception 
    # before yiedling to avoid yielding deleted objects
    try:
      obj.TypeId
    except Exception:
      pass
    else:
      yield obj


def lightSources():
  '''
  yield all light source objects in the current project.
  '''
  for obj in _allObjects():
    if ( obj.TypeId == 'App::LinkGroupPython'
            and isinstance(obj.Proxy, point_source.GenericSourceProxy) ):
      yield obj


def relevantOpticalObjects(lightSource=None, sequenceIndex=None):
  '''
  yield all optical objects in project
  '''
  # prepare sequential mode element lists
  sequentialModeEnable = False
  sequentialModeList = []
  currentObjectsOfSequence = []
  if _sett := activeSimulationSettings():
    sequentialModeEnable = _sett.SequentialMode
    sequentialModeList = _sett.Proxy.getTracingSequence(_sett)
  if sequenceIndex is not None and sequenceIndex < len(sequentialModeList):
    currentObjectsOfSequence = sequentialModeList[sequenceIndex]

  # prepare ignore lists
  ignoreList = []
  if lightSource:
    ignoreList = lightSource.IgnoredOpticalElements

  # loop through all objects and yield suitable objects
  for obj in _allObjects():
    if ( obj.TypeId == 'App::LinkGroupPython'
          and isinstance(obj.Proxy, optical_group.OpticalGroupProxy)
          and obj not in ignoreList
          and (not sequentialModeEnable
                or sequenceIndex is None
                or obj in currentObjectsOfSequence)):
      yield obj


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
