__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


import functools
import subprocess
import sys

from . import io

@functools.cache
def detectQtMajorVersion():
  if 'freecad' in sys.executable.lower():
    r = subprocess.run(['ldd', sys.executable], capture_output=True,
                       text=True, check=False)
    if 'qt5' in r.stdout.lower():
      return 5
    if 'qt6' in r.stdout.lower():
      return 6
  return None


# first try to import pyside without version, this is FreeCAD
# specific and is equivalent to the correct version of pyside
try:
  from PySide.QtCore import *
  from PySide.QtWidgets import *
  #io.verb('used module "PySide"')

except ImportError:
  # second attempt: detect Qt version then decide which pyside 
  # to import
  if detectQtMajorVersion() == 5:
    from PySide2.QtCore import *
    from PySide2.QtWidgets import *
    #io.verb('detected Qt version 5, used module "PySide2"')

  elif detectQtMajorVersion() == 6:
    from PySide6.QtCore import *
    from PySide6.QtWidgets import *
    #io.verb('detected Qt version 6, used module "PySide6"')

  # third attempt: try to import pyside6 first and try older 
  # versions on import error
  else:
    try:
      from PySide6.QtCore import *
      from PySide6.QtWidgets import *
      #io.verb('failed to detect Qt version, used module "PySide6"')
    except ImportError:
      try:
        from PySide2.QtCore import *
        from PySide2.QtWidgets import *
        #io.verb('failed to detect Qt version, used module "PySide2"')
      except ImportError:
        pass
