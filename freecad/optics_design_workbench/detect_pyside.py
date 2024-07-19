__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

'''.strip()


import functools

@functools.cache
def _detectQtMajorVersion():
  import subprocess
  import sys
  if 'freecad' in sys.executable.lower():
    r = subprocess.run(['ldd', sys.executable], capture_output=True, text=True)
    if 'qt5' in r.stdout.lower():
      return 5
    if 'qt6' in r.stdout.lower():
      return 6
  return None

# first detect Qt version then decide which pyside to import
if _detectQtMajorVersion() == 5:
  from PySide2.QtCore import *
  from PySide2.QtWidgets import *

elif _detectQtMajorVersion() == 6:
  from PySide6.QtCore import *
  from PySide6.QtWidgets import *

# if no Qt version is detectable fallback to trying to 
# import pyside6 first and try older versions on import
# error
else:
  try:
    from PySide6.QtCore import *
    from PySide6.QtWidgets import *
  except ImportError:
    try:
      from PySide2.QtCore import *
      from PySide2.QtWidgets import *
    except ImportError:
      pass
