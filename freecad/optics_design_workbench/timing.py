'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *
import time
import random
import functools

from . import io

class IntervalTimer:
  def __init__(self, interval, initialExecution=True):
    self.interval = interval
    if initialExecution:
      self.lastExecution = 0
    else:
      self.lastExecution = time.time()

  def check(self):
    if time.time() - self.lastExecution > self.interval:
      self.lastExecution = time.time()
      return True
    else:
      return False

  def wait(self):
    interruptableSleep(max([0, self.lastExecution + self.interval - time.time()]))
    self.lastExecution = time.time()

  def setLastExecution(self, t=None):
    if t is None:
      self.lastExecution = time.time()
    else:
      self.lastExecution = t

  def reset(self):
    self.setLastExecution()


class FrequencyTimer:
  def __init__(self, frequency, atol=0.1, rtol=1e-3):
    self.t0 = time.time()
    self.frequency = frequency
    self.lastT = time.time()
    self.atol = atol
    self.rtol = rtol
    self.asyncJumps = []

  def setFrequency(self, frequency):
    self.frequency = frequency

  def isSync(self):
    return len(asyncJumps) == 0

  def wait(self):
    # calculate target timestamp for next execution
    targetT = self.lastT + 1/self.frequency

    # if we are late by more than 1/f, shift targetT
    # to right now, store timestamp in asyncJumps
    # and return immediately
    if time.time()-targetT > 1/self.frequency:
      self.asyncJumps.append(time.time())
      self.asyncJumps = self.asyncJumps[-1000:]
      self.lastT = time.time()
      return True

    # calc absolute time tolerance from tolerances
    tol = max([self.rtol/self.frequency, self.atol, 1e-9])

    # to a coarse sleep until 100ms before targetT
    interruptableSleep(max([0, targetT-time.time() - 0.1]))

    # sleep single tolerance steps until targetT is reached
    while targetT-time.time() > tol/2:
      time.sleep(tol)
    self.lastT = targetT
    return True


class ProgressTracker:
  def __init__(self, total, pessimism=0):
    self.progress = 0
    self.total = total
    self.t0 = time.time()
    self.pessimism = pessimism

  def increment(self, increment=1):
    self.progress = min([self.progress+max([0, increment]), self.total])

  def set(self, progress, monotonic=True):
    if progress > self.progress or not monotonic:
      self.progress = min([max([0, progress]), self.total])

  def relative(self):
    if self.total != 0:
      return self.progress/self.total
    else:
      return 1

  def remaining(self):
    return io.secondsToStr(self._secondsRemaining())

  def elapsed(self):
    return io.secondsToStr(self._secondsElapsed())

  def doneTime(self):
    tend = time.time() + self._secondsRemaining()
    if tend < time.time() or tend > 1e10:
      return '--.--. --:--'
    else:
      return time.strftime('%d.%m. %H:%M', time.localtime(tend))

  def bar(self, width=100):
    if self.relative() < 1:
      bw = int(min([width-3, round((width-2)*self.relative())]))
      return '['+'='*bw+'>'+' '*int(width-3-bw)+']'
    else:
      return '['+'='*int(width-2)+']'

  def setTotal(self, total):
    self.total = total

  def _secondsElapsed(self):
    return time.time() - self.t0

  def _secondsRemaining(self):
    dt = self._secondsElapsed()
    return (dt/max([self.relative(), 1e-6]) - dt) * (1+self.pessimism)


class Condition:
  def __init__(self, conditionLambda, maxSize=1e3):
    self._lambda = conditionLambda
    self._log = []
    self._maxSize = maxSize

  def isTrue(self):
    value = self._lambda()
    self._log.append((time.time(), value))
    if len(self._log) > self._maxSize:
      self._log = self._log[::2]
    return value
  
  def isFalse(self):
    return not self.isTrue()

  def isTrueSince(self, sinceSecondsAgo):
    # record a value
    self.isTrue()

    # check log and select relevant values
    Ts, Bs = array(self._log).T
    _f = Ts>time.time()-sinceSecondsAgo

    # consider returning true only if at least one entry but not all are within time window
    if _f.any() and not _f.all():
      return Bs[_f].all()

    return False

  def isFalseSince(self, sinceSecondsAgo):
    # record a value
    self.isFalse()

    # check log and select relevant values
    Ts, Bs = array(self._log).T
    _f = Ts>time.time()-sinceSecondsAgo

    # consider returning true only if at least one entry but not all are within time window
    if _f.any() and not _f.all():
      return not Bs[_f].any()

    return False
