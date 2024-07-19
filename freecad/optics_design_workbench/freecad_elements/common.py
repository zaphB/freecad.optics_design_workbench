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

import time

from ..detect_pyside import QApplication
from .. import simulation

_LAST_PROCESS_EVENTS_CALL = time.time()
_MIN_UPDATE_INTERVAL = 1e-2

class SimulationCanceled(RuntimeError):
  pass

def processGuiEvents():
  global _LAST_PROCESS_EVENTS_CALL
  if QApplication.instance() and time.time()-_LAST_PROCESS_EVENTS_CALL > _MIN_UPDATE_INTERVAL:
  
    # process Qt events
    QApplication.processEvents()
    _LAST_PROCESS_EVENTS_CALL = time.time()

    # check wether simulation was canceled and raise SimulationCanceled if so
    if simulation.isCanceled():
      raise SimulationCanceled()

def updateGui():
  if QApplication.instance():
    QApplication.processEvents()
    QApplication.processEvents()
    Gui.updateGui()
    QApplication.processEvents()
    QApplication.processEvents()
