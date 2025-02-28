'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *

import threading
import time
import os
import pickle
import traceback

from .. import io

try:
  import IPython.display
  hasIPython = True
except ImportError:
  hasIPython = False

ALLOW_PROGRESS_TACKERS = False
_GLOBAL_PROGRESS_TRACKER = None

def setupProgressTracker(**kwargs):
  '''
  Create a new global progress tracker for usage in jupyter notebooks
  '''
  global _GLOBAL_PROGRESS_TRACKER

  # raise if progress tracker creation is not allowed (=we are not in a FreecadDocument context)
  if not ALLOW_PROGRESS_TACKERS:
    raise ValueError(f'progress tracking can only be setup within FreecadDocument(..) contexts')

  # quit existing progress tracker if any
  if _GLOBAL_PROGRESS_TRACKER is not None and not _GLOBAL_PROGRESS_TRACKER._isQuit:
    _GLOBAL_PROGRESS_TRACKER.quit()
  
  # make sure new progress tracker is silent if older one was silent
  if _GLOBAL_PROGRESS_TRACKER is not None and _GLOBAL_PROGRESS_TRACKER._silent:
    kwargs.update(dict(silent=True))

  # create new progress tracker
  _GLOBAL_PROGRESS_TRACKER = _ProgressTacker(**kwargs)

  # return global instance
  return _GLOBAL_PROGRESS_TRACKER

def silenceProgressTracker():
  setupProgressTracker(silent=True)

def progressTrackerExists():
  return _GLOBAL_PROGRESS_TRACKER is not None and not _GLOBAL_PROGRESS_TRACKER._isQuit

def progressTrackerInstance(**kwargs):
  '''
  Fetch the current global progressTrackerInstance
  '''
  if _GLOBAL_PROGRESS_TRACKER is None or _GLOBAL_PROGRESS_TRACKER._isQuit:
    setupProgressTracker(**kwargs)
  return _GLOBAL_PROGRESS_TRACKER

def clearCellOutput():
  IPython.display.clear_output(True)


class _ProgressTacker:
  def __init__(self, doc=None, totalSimulations=None, silent=False):
    self._doc = doc
    self._simulationNo = 0
    self._totalSimulations = totalSimulations
    self._isRunning = True
    self._isQuit = False
    self._clearCallCount = 0
    self._t = threading.Thread(target=self.updateLoop)
    self._t0 = time.time()
    self._previousProgressDict = None
    self._silent = silent
    self.resultsFolder = None
    self.start()

  def _clear(self):
    # Do not clear output on the first calls to clear, because this would
    # erase exception stacktraces that may be raised in the very first few
    # iterations of a simulation loop in the jupyter cell. 
    self._clearCallCount += 1
    if not self._silent and hasIPython and self._clearCallCount > 5:
      IPython.display.clear_output(True)

  def start(self):
    self._clear()
    #print('setting up simulation progress tracking...')
    self._t.start()
    self._t0 = time.time()

  def update(self, displayTiming=True):
    if self._silent:
      return

    if self.resultsFolder:
      try:
        latest = sorted([f for f in os.listdir(f'{self.resultsFolder._path}/progress')
                                                      if f.startswith('master') ])[-1]
        with open(f'{self.resultsFolder._path}/progress/{latest}', 'rb') as _f:
          p = pickle.load(_f)
        self._previousProgressDict = p
      except (FileNotFoundError, IndexError):
        p = self._previousProgressDict or dict(
                  totalIterations=nan, endAfterIterations=nan,
                  totalRecordedHits=nan, endAfterHits=nan,
                  totalTracedRays=nan, endAfterRays=nan)
      except Exception:
        io.warn(traceback.format_exc())

      # calculate elapsed and expected remaining time
      elapsed = time.time()-self._t0
      simulationProg = max([ p['totalIterations']/p['endAfterIterations'],
                              p['totalRecordedHits']/p['endAfterHits'],
                              p['totalTracedRays']/p['endAfterRays'] ])
      if not isfinite(simulationProg):
        simulationProg = 0
      relProgress = (self._simulationNo + simulationProg)/(self._totalSimulations or 1)
      expectedRemain = inf
      if relProgress > 0:
        expectedRemain = elapsed/relProgress * (1-relProgress)
      if expectedRemain > elapsed**2:
        expectedRemain = None

      # generate progress message
      self._clear()
      iterationProgress = ''
      if self._totalSimulations:
        iterationProgress = f'simulations done {self._simulationNo}/{self._totalSimulations}'
      simulationProgress = ''
      if isfinite(p['totalIterations']):
        simulationProgress = (f'current simulation: '
                              f"iter {p['totalIterations']}/{p['endAfterIterations']}, "
                              f"hits {p['totalRecordedHits']}/{p['endAfterHits']}, "
                              f"rays {p['totalTracedRays']}/{p['endAfterRays']}")
      message = ', '.join([s for s in (iterationProgress, simulationProgress) if s.strip()])

      # print progress message
      printedSomething = False
      if message.strip():
        print(message)
        printedSomething = True
      if displayTiming:
        print(f'elapsed time {io.secondsToStr(elapsed)}'
              +(f', expected remaining time {io.secondsToStr(expectedRemain)}' 
                                        if expectedRemain is not None else ''))
        printedSomething = True

      # return whether something was printed or not
      return printedSomething

  def updateLoop(self):
    while self._isRunning:
      self.update()
      time.sleep(1/3)
    if self.update(displayTiming=False):
      print(f'simulations ended after {io.secondsToStr(time.time()-self._t0)}')

  def nextIteration(self):
    self._simulationNo += 1

    # reset buffered progress dict to not display progress of previous iteration
    self._previousProgressDict = None

    # if total iterations was never specified, quit 
    # this progress tracker such that a new one is
    # created in the next iteration (if any)
    if self._totalSimulations is None:
      self.quit()
  
  def quit(self):
    self._isRunning = False
    self._t.join()
    self._isQuit = True
