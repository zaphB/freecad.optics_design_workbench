'''
Classes/functions handling the simulation loop, saving of results, progress tracking, background workers, etc. Submodules in here use the FreeCAD.App and Gui objects in a few places but only to fetch paths or similar metadata, not for direct interaction with FreeCAD. For direct interaction prefer to use submodules of freecad_elements.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from .processes import *
from .results_store import *
from . import tracing_cache

def makeGoodRandomSeed():
  '''
  Make sure python and numpy random number generators both have 
  seeds that differ across threads and processes.
  '''

  import random
  import numpy.random
  import os
  import threading
  import time

  seed = int(str(threading.get_ident())+str(os.getpid())+str(int(1e7*time.time()))[-10:]) % (2**32)
  random.seed(seed)
  numpy.random.seed(seed)

# run on module load
makeGoodRandomSeed()
