'''
Definitions for behavior/objects/commands living in the FreeCAD projects. The ray-tracing code is in here, because it is inherently connected to the FreeCAD geometry engine.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from .point_source import *
from .surface_source import *
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
  loadSurfaceSource()
  loadReplaySource()
  loadGroups()
  loadSimulationSettings()
  loadSimulationActions()


def collectGlobalInfo():
  '''
  Build dictionary containing globally relevant info about simulation project.
  '''
  res = {}
  
  # helper function to extract all properties of a freecad obj and 
  # create a dict
  def objPropertiesToDict(obj, toplevel=True):
    def robustGetattr(o, k):
      try:
        res = getattr(o, k, None)
        if not hasattr(res, '__dict__') and not hasattr(res, '__call__') and not hasattr(res, '__iter__'):
          try:
            pickle.dumps(res)
          except Exception:
            return str(res)
        return res
      except Exception:
        return '<failed to export>'

    # helper to decide whether obj,k pair should be exported 
    isValid = lambda obj, k: (not k.startswith('_')
          and not k.startswith('Attach')
          and k not in ('Placement Proxy Shape ShapeMaterial '
            'ColoredElements ElementList ExpressionEngine '
            'LinkedChildren VisibilityList Visibility Height '
            'Length Width MapMode MapPathParameter '
            'MapReversed').split()
          and not hasattr(robustGetattr(obj, k), '__call__'))

    # cannot use values __dict__, these are empty
    if hasattr(obj, '__dict__'):
      return {k: objPropertiesToDict(robustGetattr(obj, k))
                    for k in list(obj.__dict__.keys())+['Name']
                        if isValid(obj, k)} 
    # recurse into lists
    if hasattr(obj, '__iter__') and type(obj) not in (str, str_):
      return [objPropertiesToDict(v) for v in obj]
    return obj

  # helper to bundle properties and transforms to one dict
  def objToDict(obj, ignoreLinks=False):
    print(obj)
    properties = objPropertiesToDict(obj)
    placementPaths = [p for _, p in allPlacementsAndPaths(obj, ignoreLinks=ignoreLinks)]
    matrices = [[matrixToArray(m) for m in M] 
                  for M in allCoordinateTransformMatrices(obj, ignoreLinks=ignoreLinks)]
    return dict(
      name=properties.pop('Name'),
      label=properties.pop('Label'),
      properties=properties,
      placementPathsAndMatrices=[
        dict(path=path,
             gpM=m[0], gpMi=m[1], pM=m[2], pMi=m[3])
                  for path, m in zip(placementPaths, matrices)]
    )

  # add simulation settings content
  res['activeSimulationSettings'] = objPropertiesToDict(find.activeSimulationSettings())

  # find all light sources and their coordinate transform matrices
  res['lightSources'] = [objToDict(s, ignoreLinks=True) for s in find.lightSources()]

  # add all optical elements and their coordinate transform matrices
  res['opticalObjects'] = [objToDict(o) for o in find.opticalObjects()]

  # return dictionary
  return res