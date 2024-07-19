__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

Classes/functions handling the simulation process(es).

The GUI simulations all take place in the GUI main thread using the "QApplication.processEvents"-hack to keep the GUI responsive. The extra implementation work for a proper QRunnable/QThreadpool solution is not worth it (yet), because it would only improve the responsiveness, not the actual simulation performance because of python's GIL.

To do simulations with actual performance gain, background processes running headless FreeCADCmd are launched in the background.

'''.strip()


try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

try:
  from PySide6.QtWidgets import QApplication
  from PySide6.QtCore import QProcess, QTimer
except:
  from PySide2.QtWidgets import QApplication
  from PySide2.QtCore import QProcess, QTimer

from numpy import *
import time
import datetime
import functools
import subprocess
import os
import sys
import threading
import signal

from .. import freecad_elements
from .. import gui_windows
from . import results_store

_SIMULATION_RUNNING = False
_SIMULATION_CANCELED = False
_WORKER_INDEX = 0
_BACKGROUND_PROCESSES = []

def isWorkerRunning():
  #print(isCanceled(), [w.isRunning() for w in _BACKGROUND_PROCESSES])
  _BACKGROUND_PROCESSES[:] = [w for w in _BACKGROUND_PROCESSES if w.isRunning()]
  return len(_BACKGROUND_PROCESSES)

def isRunning():
  return bool(_SIMULATION_RUNNING)

def isCanceled():
  return _SIMULATION_CANCELED

def cancelSimulation():
  global _SIMULATION_CANCELED
  if isRunning():
    _SIMULATION_CANCELED = True

def logMsg(msg):
  print(datetime.datetime.now().strftime('[%H:%M:%S.%f] ')+msg)

def runAction(action, simulationRunFolder=None, _isMaster=True, _isWorkerOf=False):
  global _SIMULATION_RUNNING, _SIMULATION_CANCELED
  t0 = time.time()

  # all commands that start some sort of simulation:
  if action in ('fans', 'singlepseudo', 'singletrue', 'pseudo', 'true'):

    # recompute document
    App.ActiveDocument.recompute()

    # determine simulation mode
    mode = action
    if action.startswith('single'):
      mode = action[6:]
    
    iterations = 1
    # determine iteration count
    if action in ('pseudo', 'true'):  
      iterations = inf

    # for continuous modes set global vars to respective state
    if iterations > 1:
      _SIMULATION_CANCELED = False
      _SIMULATION_RUNNING = True

    # determine whether to store results or not
    store = False
    storeSingleShot = False
    if settings := freecad_elements.find.activeSimulationSettings():
      storeSingleShot = settings.EnableStoreSingleShotData
    if action in ('singlepseudo', 'singletrue', 'fans'):
      store = storeSingleShot
    if action in ('pseudo', 'true'):
      store = True

    # determine whether to draw rays or not
    draw = True
    drawContinuous = False
    if settings := freecad_elements.find.activeSimulationSettings():
      drawContinuous = settings.ShowRaysInContinuousMode
    if action in ('pseudo', 'true'):
      draw = drawContinuous

    # force draw to true if no QApplication is present to not branch into part
    # that required QTimer later
    if QApplication.instance() is None:
      draw = True

    # determine number if workers to spawn (single for single shot simulations, 
    # according to settings for more than one iteration)
    workers = 1
    if iterations > 1 and (settings := freecad_elements.find.activeSimulationSettings()):
      if settings.WorkerProcessCount == 'num_cpus':
        workers = cpuCount()
      else:
        workers = int(settings.WorkerProcessCount)

    # find limits if any to stop simulation
    maxIterations = 10
    maxRays = inf
    maxHits = inf
    if settings := freecad_elements.find.activeSimulationSettings():
      _parse = lambda x: int(x) if x!='inf' else inf
      maxIterations = _parse(settings.EndAfterIterations)
      maxRays = _parse(settings.EndAfterRays)
      maxHits = _parse(settings.EndAfterHits)

    # generate simulation run folder name
    if simulationRunFolder is None:
      simulationRunFolder = results_store.generateSimulationFolderName()

    # generate store object and open a gui window for it (if this is not run by worker)
    if store:
      store = results_store.SimulationResults(simulationType=mode, simulationRunFolder=simulationRunFolder,
                                              maxIterations=maxIterations, maxRays=maxRays, maxHits=maxHits)

      # connect progress window to this store if more than one iteration is requested
      if _isMaster and iterations > 1:
        gui_windows.showProgressWindow(store)   

    # launch background worker processes (one less than specified if draw is true because then the
    # master process will also work), only launch if we are the master process
    if _isMaster:
      if draw:
        backgroundWorkers = workers-1
      else:
        backgroundWorkers = workers
      for workerNo in range(backgroundWorkers):
        #logMsg('launching background worker...')
        _BACKGROUND_PROCESSES.append(WorkerProcess(simulationType=mode, simulationRunFolder=simulationRunFolder))
        for _ in range(50):
          freecad_elements.updateGui()
          time.sleep(.01)

    # make sure document is saved if more than one worker is requested and we are the master
    # and we are running a GUI, which means we actually might have unsaved changes
    if workers > 1 and _isMaster and QApplication.instance() is not None:
      App.ActiveDocument.save()

    canceledAt = None
    def pollIfSimulationDone(t0, quiet=False):
      global _SIMULATION_CANCELED, _SIMULATION_RUNNING
      nonlocal canceledAt
      if isWorkerRunning():
        freecad_elements.updateGui()
        if isCanceled():
          if canceledAt is None:
            canceledAt = time.time()
          for w in _BACKGROUND_PROCESSES:
            # first try quit (place job-is-done file), 
            # then terminate (SIGTERM), then kill (SIGKILL)
            if time.time()-canceledAt < 7:
              w.quit()
            elif time.time()-canceledAt < 10:
              w.terminate()
            else:
              w.kill()
        return False
      else:
        #print('stop simulation triggered...')
        _SIMULATION_CANCELED = False
        results_store.placeJobDoneFile(simulationRunFolder)
        if hasattr(_SIMULATION_RUNNING, 'stop'):
          _SIMULATION_RUNNING.stop()
        _SIMULATION_RUNNING = False
        return True

    # report to shell that simulation starts
    logMsg(f'starting simulation {mode=}, {store=}, {draw=}, {workers=}, iterations={min([iterations, maxIterations])}')

    # this block does the simulation in the FreeCAD process with GUI updating etc
    # this shall only be called if draw is actually true
    if draw or not _isMaster:
      # wrap simulation in try-finally to make absolutely sure that 
      # dataset is flushed and ended finally
      try:
        iteration = 0
        while True:
          # increment counter and cancel if enough iterations were run
          if iteration >= iterations:
            break
          iteration += 1

          # do ray-tracing for all light sources
          for obj in freecad_elements.find.lightSources():

            # run actual iteration
            obj.Proxy.runIteration(obj, mode=mode, draw=draw, store=store)

            # raise simulation canceled exception if parent PID is not alive
            if not _isMaster:
              try:
                os.kill(_isWorkerOf, 0)
              except OSError:
                logMsg(f'parent pid {_isWorkerOf} seems to have exited, exiting as well...')
                raise freecad_elements.SimulationCanceled

            # stop if we are not the _master process and job-is-done file appeared
            if results_store.jobDoneFileExists(simulationRunFolder):
              logMsg('job done file was found, seems we are done here, exiting...')
              raise freecad_elements.SimulationCanceled

            # stop if run was canceled
            if isCanceled():
              logMsg('someone called cancelSimulation(), exiting...')
              raise freecad_elements.SimulationCanceled

          if store:
            # tell storage object that iteration is done
            store.incrementIterationCount()

            # makes sure disk writes are happening (without this line no progress would be written
            # to disk in rare case without any .addRay or .addRayHit calls)
            store.writeDiskIfNeeded()

            if _isMaster:
              # make sure progress is updated in master process (this will also trigger 
              # cancelSimulation if one of the specified ends criteria is reached)
              store.getProgress()
          
      except freecad_elements.SimulationCanceled:
        pass

      except Exception:
        cancelSimulation()
        raise

      finally:
        # flush yet unflushed results to disk (if store is active)
        if store:
          store.flush()

        # log summary of simulation run
        graceful = not isCanceled() or (store and store.reachedMax)
        logMsg(f'simulation {"ended gracefully" if graceful else "was canceled"} '
               f'after {time.time()-t0:.1e}s at {iteration=} '
               f'({60*60*iteration/(time.time()-t0):.1e} iters/hour)')

        # for continuous modes set global vars to respective state
        if iterations > 1:
          t0 = time.time()
          printedYet = False
          while not pollIfSimulationDone(t0):
            time.sleep(1e-2)
            if time.time()-t0 > 0.3 and isWorkerRunning() and not printedYet:
              logMsg('waiting for workers to finish...')
              printedYet = True
    
    # if draw is false but we are in a Qt application, start a QTimer that updates the progress:
    elif QApplication.instance():
      t0 = time.time()
      def updateProgress():
        if store and _isMaster:
          # make sure progress is updated (this will also trigger cancelSimulation if one 
          # of the specified ends criteria is reached)
          store.getProgress()

        # poll if any worker is still running and stop this timer if not the case
        pollIfSimulationDone(t0, quiet=True)

      _SIMULATION_RUNNING = QTimer()
      _SIMULATION_RUNNING.timeout.connect(updateProgress)
      _SIMULATION_RUNNING.start(300)

  elif action == 'stop':
    logMsg('canceling simulation...')
    cancelSimulation()

  else:
    raise ValueError(f'unexpected {action=}')


class WorkerProcess:
  def __init__(self, simulationType, simulationRunFolder):
    # set index for worker process for easy identification in cli logs
    global _WORKER_INDEX
    self.index = _WORKER_INDEX
    _WORKER_INDEX += 1

    # start freecad in cli mode (-c) with current document as active document
    self.simulationType = simulationType
    self.simulationFilePath = os.path.realpath(App.activeDocument().getFileName())
    self.simulationRunFolder = simulationRunFolder
    self._isRunning = True

    # try to extract freecad executable path, by default let shell decide
    freecadPath = 'freecad'
    if 'freecad' in sys.executable.lower():
      freecadPath = sys.executable

    # launch child process
    self._p = subprocess.Popen([freecadPath, '-c', self.simulationFilePath],
                                #stdout=subprocess.DEVNULL,
                                #stderr=subprocess.DEVNULL,
                                stdin=subprocess.PIPE, 
                                text=True, bufsize=-1)

    # write python snippet to start desired simulation mode
    self.say('entering simulation loop...')
    self.write(f'\r\n'
               f'import freecad.optics_design_workbench\r\n'
               f'freecad.optics_design_workbench.simulation.runAction('
                      f'action="{self.simulationType}", '
                      f'simulationRunFolder="{self.simulationRunFolder}", '
                      f'_isMaster=False, '
                      f'_isWorkerOf={os.getpid()})\r\n'
               f'exit()\r\n')

    self._isquit = False
    self._isterminate = False
    self._iskill = False


  def write(self, data):
    self._p.stdin.write(data)
    self._p.stdin.flush()

  def say(self, msg):
    if type(msg) is not str:
      msg = bytes(msg).decode('utf8')
    for line in msg.split('\n'):
      line = line.strip().strip('>').strip()
      if len(line):
        logMsg(f'worker ({self.index}) says: '+line)

  def isRunning(self):
    if self._isRunning:
      if (res:=self._p.poll()) is not None:
        self._isRunning = False
        self.say(f'finished (exit code {res})')
    return self._isRunning

  def quit(self):
    if self.isRunning() and not self._isquit:
      self.say('asking FreeCAD to quit...')
      results_store.placeJobDoneFile(self.simulationRunFolder)
      self._isquit = True

  def terminate(self):
    if self.isRunning():
      if not self._isterminate:
        self.say('terminating FreeCAD...')
        self._isterminate = True
      try:
        self._p.stdin.close()
      except:
        pass
      self._p.send_signal(signal.SIGTERM)

  def kill(self):
    if self.isRunning():
      if not self._iskill:
        self.say('killing FreeCAD...')
        self._iskill = True
      self._p.send_signal(signal.SIGKILL)


@functools.cache
def cpuCount():
  # try analyze lscpu output
  threadsPerCore = None
  coresPerSocket = None
  sockets = None
  try:
    for l in subprocess.run('lscpu', check=False, capture_output=True, text=True).stdout.split('\n'):
      if 'thread' in l.lower() and 'per core' in l.lower():
        threadsPerCore = int(l.split(':')[-1].strip())
      elif 'core' in l.lower() and 'per sock' in l.lower():
        coresPerSocket = int(l.split(':')[-1].strip())
      elif 'socket' in l.lower():
        sockets = int(l.split(':')[-1].strip())
  except Exception:
    pass

  # return number of physical cores
  if threadsPerCore and coresPerSocket and sockets:
    return coresPerSocket * sockets

  # alternatively just use standard python modules for cpu count 
  # and divide result by two because virtually all cpus use two
  # threads per core
  try:
    count = len(os.sched_getaffinity(0))
  except Exception:
    count = os.cpu_count()  
  return max([1, count//2])
