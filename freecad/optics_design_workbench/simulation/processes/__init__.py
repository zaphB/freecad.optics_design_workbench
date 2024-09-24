'''
This module contains classes/functions handling the simulation process(es).

The GUI simulations all take place in the GUI main thread using the 
"QApplication.processEvents"-hack to keep the GUI responsive. The extra
implementation work for a proper QRunnable/QThreadpool solution is 
not worth it (yet), because it would only improve the responsiveness,
not the actual simulation performance because of python's GIL.

To do simulations with actual performance gain, background processes
running headless FreeCADCmd are launched in the background.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from .simulation_loop import *
from .worker_process import *
