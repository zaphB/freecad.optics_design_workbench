__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

import time

from .. import simulation

_LAST_PROCESS_EVENTS_CALL = time.time()
_MIN_UPDATE_INTERVAL = 1e-2

class SimulationEnded(RuntimeError):
  pass

def keepGuiResponsive(raiseIfSimulationDone=False):
  from ..detect_pyside import QApplication  
  global _LAST_PROCESS_EVENTS_CALL
  if time.time()-_LAST_PROCESS_EVENTS_CALL > _MIN_UPDATE_INTERVAL:
    _LAST_PROCESS_EVENTS_CALL = time.time()

    if QApplication.instance():
      # process Qt events
      QApplication.processEvents()
      Gui.updateGui()
      QApplication.processEvents()

    # check whether simulation was canceled and raise SimulationEnded if so
    if raiseIfSimulationDone and (simulation.isCanceled() or simulation.isFinished()):
      raise SimulationEnded()
      
def keepGuiResponsiveAndRaiseIfSimulationDone():
  keepGuiResponsive(raiseIfSimulationDone=True)
