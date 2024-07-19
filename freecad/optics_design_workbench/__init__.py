__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

'''.strip()


import functools
from .version import __version__

def _ensureSystemPackagesCanBeImported():
  '''
  make sure system packages are importable (this is important if e.g. AppImage versions are used)
  '''
  import sys
  import os
  ma, mi = sys.version_info.major, sys.version_info.minor
  found = False

  # look for site-packages folder matching current python version, or one of the three previous 
  # minor python versions or the next minor python version
  for d in (0, -1, -2, -3, 1):

    # some systems call it /usr/lib64, some call it /usr/lib, therefore check both
    for w in ('64', ''):

      # check candidate paths and add if needed
      candidate = os.path.realpath(f'/usr/lib{w}/python{ma}.{mi+d}/site-packages')
      if os.path.exists(candidate):
        if candidate not in sys.path:
          print(f'freecad.optics_design_workbench: python package path {candidate} exists on filesystem but not in sys.path, appending to sys.path...')
          sys.path.append(candidate)

        # stop looking after the first candidate existed on disk
        found = True
        break
    if found:
      break

# run on module load
_ensureSystemPackagesCanBeImported()

def versionInfo():
  '''
  print summary of version numbers that may be relevant for the workbench
  '''
  import sys
  import os
  FreeCAD = None
  try:
    import FreeCAD
  except ImportError:
    pass
  from . import detect_pyside
  print(f'executable path:   {os.path.realpath(sys.executable)}')
  print(f'python version:    {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')
  print(f'freecad version:   {".".join(FreeCAD.Version()[:3]) if FreeCAD else "?"}')
  print(f'Qt major version:  {detect_pyside._detectQtMajorVersion() or "?"}')
  print(f'workbench version: {__version__}')
