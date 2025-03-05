__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__version__ = None

def _determinePackageVersion():
  '''
  find out installed version of the workbench and set global variable
  '''
  global __version__
  from importlib.metadata import version
  try:
    __version__ = version('optics_design_workbench')
  except Exception:
    try:
      __version__ = version('freecad.optics_design_workbench')
    except Exception:
      __version__ = '?'

# make sure __version__ is set
_determinePackageVersion()


def _ensureSystemPackagesCanBeImported():
  '''
  make sure system packages are importable (this is important if e.g. AppImage versions are used)
  '''
  import sys
  import os
  ma, mi = sys.version_info.major, sys.version_info.minor
  found = False

  # do not add system folders if we seem to run from a venv
  if sys.prefix != sys.base_prefix:
    return

  # look for site-packages folder matching current python version, or one of the three previous
  # minor python versions or the next minor python version
  for d in (0, -1, -2, -3, 1):

    # some systems call it /usr/lib64, some call it /usr/lib, therefore check both
    for w in ('64', ''):

      # check candidate paths and add if needed
      candidate = os.path.realpath(f'/usr/lib{w}/python{ma}.{mi+d}/site-packages')
      if os.path.exists(candidate):
        if candidate not in sys.path:
          print(f'[freecad.optics_design_workbench] python package path {candidate} exists on '
                f'filesystem but not in sys.path, appending to sys.path...')
          sys.path.append(candidate)

# run on module load
_ensureSystemPackagesCanBeImported()

def versionInfo():
  '''
  print summary of version numbers that may be relevant for the workbench
  '''
  import sys
  import os
  FreeCAD = None
  freecadVersion = None
  try:
    import FreeCAD
  except ImportError:
    pass
  else:
    freecadVersion = ".".join(FreeCAD.Version()[:3])
  if freecadVersion is None:
    from . import jupyter_utils
    freecadVersion = jupyter_utils.freecadVersion()
  from . import detect_pyside
  print(f'python version:          {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')
  print(f'workbench version:       {__version__}')
  print(f'FreeCAD version:         {freecadVersion or "?"}')
  print(f'running within FreeCAD?  {"yes" if FreeCAD else "no"}')
  if detect_pyside.detectQtMajorVersion():
    print(f'Qt major version:        {detect_pyside.detectQtMajorVersion()}')
  print(f'sys.prefix:              {sys.prefix}')
  print(f'sys.base_prefix:         {sys.base_prefix}')
