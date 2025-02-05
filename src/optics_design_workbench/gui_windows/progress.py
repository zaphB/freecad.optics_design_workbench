__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *
import pickle
import time
import os

from ..detect_pyside import *
from . import common

_PROGRESS_WINDOW = None


def secondsToYMDhms(secs):
  res = []
  for mult in [365*24*60*60, 30*24*60*60, 24*60*60, 60*60, 60, 1]:
    res.append(int(secs/mult))
    secs -= res[-1]*mult
  return res

def secondsToStr(secs, length=2):
  res = []
  split = secondsToYMDhms(secs)
  for num, label in zip(split,
                        ['Y', 'M', 'd', 'h', 'm', 's']):
    if res or num or label=='s':
      res.append(str(num) + label)
  return ' '.join(res[:length])

def scaleSuff(x):
  if x >= 2e9:
    return 1e-9, 'G'
  if x >= 2e6:
    return 1e-6, 'M'
  if x >= 2e3:
    return 1e-3, 'k'
  return 1, ''

class QLabeledProgress(QProgressBar):
  def __init__(self, label, maximum=None):
    super().__init__()
    self.setRange(0,1)
    self.maximum = maximum or inf
    self.label = label
    self.t0 = time.time()
    self.remainingSeconds = None
    self.lastVal = None

  def setValue(self, val):
    self.lastVal = val
    scale, suff = scaleSuff(val)

    # decide out how many digits to show
    digits = 2
    if val*scale>=10:
      digits = 1
    if val*scale>=1e2 or scale==1:
      digits = 0

    # show progress including target value
    if isfinite(self.maximum):
      if time.time()-self.t0 > 5 and val > 0:
        self.remainingSeconds = (time.time()-self.t0)/val * max([self.maximum-val, 0])
      self.setRange(0, max([val+1e-2, self.maximum]))
      mscale, msuff = scaleSuff(self.maximum)
      # decide how many digits to show for maximum
      mdigits = 1
      if self.maximum*mscale>=10 or mscale==1:
        mdigits = 0
      self.setFormat(f'{self.label}: {val*scale:.{digits}f}{suff}'
                     f' / {self.maximum*mscale:.{mdigits}f}{msuff}')
      super().setValue(val)

    # or just show number and never increment bar
    else:
      self.setFormat(f'{self.label}: {val*scale:.{digits}f}{suff}')
      super().setValue(0)


class ProgressWindow(QWidget):
  '''
  ProgressWindows are linked to a SimulationResults instance and constantly 
  consume the progress files being dumped into the progress directory. The contents
  of the consumed files will then be displayed in the window.
  '''
  def __init__(self):
    # setup window contents
    super().__init__()
    self.setWindowTitle('FreeCAD Optics Design Workbench simulation progress')
    layout = QVBoxLayout()
    self.label = QLabel()
    layout.addWidget(self.label)
    self.lastUpdatedLabel = 0

    self.iterations = QLabeledProgress('iterations')
    layout.addWidget(self.iterations)

    self.raysTraced = QLabeledProgress('rays')
    layout.addWidget(self.raysTraced)

    self.hitsRecorded = QLabeledProgress('recorded hits')
    layout.addWidget(self.hitsRecorded)

    self.setLayout(layout)

    # setup timer to consume files
    self.timer = QTimer()
    self.timer.timeout.connect(self.onTimer)
    self.timer.start(50)

  def setStore(self, store):
    self.store = store
    if any([isfinite(m) for m in (store.endAfterIterations, store.endAfterRays, store.endAfterHits)]):
      self.label.setText('simulation progress (approx. ..... remain)')
    else:
      self.label.setText('simulation progress (running infinitely)')
    self.iterations.maximum = store.endAfterIterations
    self.raysTraced.maximum = store.endAfterRays
    self.hitsRecorded.maximum = store.endAfterHits
    self.iterations.t0 = time.time()
    self.iterations.remainingSeconds = None
    self.raysTraced.t0 = time.time()
    self.raysTraced.remainingSeconds = None
    self.hitsRecorded.t0 = time.time()
    self.hitsRecorded.remainingSeconds = None
    self.timer.start(50)

  def onTimer(self):
    progress = self.store.getProgress()
    remainingSeconds = inf

    # update all progress bars
    for bar, key in [(self.iterations,   'totalIterations'),
                     (self.raysTraced,   'totalTracedRays'),
                     (self.hitsRecorded, 'totalRecordedHits'),
                    ]:
      # calculate sum of all workers
      bar.setValue(progress.get(key, 0))

      # if bar offers remaining seconds field show it
      if bar.remainingSeconds is not None:
        remainingSeconds = min([remainingSeconds, bar.remainingSeconds])

    if remainingSeconds < 1e9 and time.time()-self.lastUpdatedLabel > .5:
      self.label.setText(f'simulation progress (approx. {secondsToStr(remainingSeconds)} remain)')
      self.lastUpdatedLabel = time.time()

    # stop timer if simulation is not running
    if not self.store.isSimulationRunning():
      status = 'done' if self.store.simulationEndedGracefully() else 'canceled'
      self.label.setText(f'simulation progress ({status})')
      self.timer.stop()


def showProgressWindow(store):
  global _PROGRESS_WINDOW
  
  # ignore call if gui windows are set to be hidden
  if common.HIDE_GUI:
    return

  # only create window if inside a QtApp
  if QApplication.instance() is not None:
    if _PROGRESS_WINDOW is None:
      _PROGRESS_WINDOW = ProgressWindow()
    _PROGRESS_WINDOW.setStore(store)
    _PROGRESS_WINDOW.show()
