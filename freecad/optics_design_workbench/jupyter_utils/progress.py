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

  # raise if progress tracker creation is not allows (=we are not in a FreecadDocument context)
  if not ALLOW_PROGRESS_TACKERS:
    raise ValueError(f'progress tracking can only be setup within FreecadDocument(..) contexts')

  # quit existing progress tracker if any
  if _GLOBAL_PROGRESS_TRACKER is not None and not _GLOBAL_PROGRESS_TRACKER._isQuit:
    _GLOBAL_PROGRESS_TRACKER.quit()
  _GLOBAL_PROGRESS_TRACKER = _ProgressTacker(**kwargs)

  # return global instance
  return _GLOBAL_PROGRESS_TRACKER

def progressTrackerInstance(**kwargs):
  '''
  Fetch the current global progressTrackerInstance
  '''
  if _GLOBAL_PROGRESS_TRACKER is None or _GLOBAL_PROGRESS_TRACKER._isQuit:
    setupProgressTracker(**kwargs)
  return _GLOBAL_PROGRESS_TRACKER


class _ProgressTacker:
  def __init__(self, doc=None, totalSimulations=None):
    self._doc = doc
    self._simulationNo = 0
    self._totalSimulations = totalSimulations
    self._isRunning = True
    self._isQuit = False
    self._t = threading.Thread(target=self.updateLoop)
    self._t0 = time.time()
    self.resultsFolder = None
    self.start()

  def _clear(self):
    if hasIPython:
      IPython.display.clear_output(True)

  def start(self):
    self._clear()
    print('setting up simulation progress tracking...')
    self._t.start()
    self._t0 = time.time()

  def update(self):
    if self.resultsFolder:
      try:
        latest = sorted([f for f in os.listdir(f'{self.resultsFolder._path}/progress')
                                                      if f.startswith('master') ])[-1]
        with open(f'{self.resultsFolder._path}/progress/{latest}', 'rb') as _f:
          p = pickle.load(_f)
      except (FileNotFoundError, IndexError):
        pass
      except Exception:
        io.warn(traceback.format_exc())
      else:
        # calculate elapsed and expected remaining time
        elapsed = time.time()-self._t0
        simulationProg = max([ p['totalIterations']/p['endAfterIterations'],
                               p['totalRecordedHits']/p['endAfterHits'],
                               p['totalTracedRays']/p['endAfterRays'] ])
        relProgress = (self._simulationNo + simulationProg)/(self._totalSimulations or 1)
        expectedRemain = None
        if relProgress > 0:
          expectedRemain = elapsed/relProgress * (1-relProgress)
        if expectedRemain > elapsed**2:
          expectedRemain = None

        # print message
        self._clear()
        prefix = ''
        if self._totalSimulations:
          prefix = f'simulation {self._simulationNo}/{self._totalSimulations}, current '
        print(prefix+f'simulation: iter {p['totalIterations']}/{p['endAfterIterations']}, '
              f'hits {p['totalRecordedHits']}/{p['endAfterHits']}, '
              f'rays {p['totalTracedRays']}/{p['endAfterRays']}')
        print(f'elapsed time {io.secondsToStr(elapsed)}'
              +(f', expected remaining time {io.secondsToStr(expectedRemain)}' 
                                        if expectedRemain is not None else ''))

  def updateLoop(self):
    while self._isRunning:
      self.update()
      time.sleep(.5)
    print(f'simulations ended after {io.secondsToStr(time.time()-self._t0)}')

  def nextIteration(self):
    self._simulationNo += 1

    # if total iterations was never specified, quit 
    # this progress tracker such that a new one is
    # created in the next iteration (if any)
    if self._totalSimulations is None:
      self.quit()
  
  def quit(self):
    self._isRunning = False
    self._t.join()
    self._isQuit = True
