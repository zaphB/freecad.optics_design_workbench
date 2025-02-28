'''
This module handles the simulation loop. It implements the mainloop
of the simulation and functions to start/stop/query the status for
the GUI. Only one single simulation loop can run at a time, i.e. no
fan preview is possible while another job is running.

Terminology in this module:
* master process: process that launches workers, tracks progress and 
                  cleans up in the end. The master may or may not run
                  the GUI, and it may or may not contribute to the
                  simulation work, depending how the simulation was started.
* worker process: background processes launched with subprocess module
                  that run FreeCAD in headless mode and run simulation work.
* simulation: ray-tracing procedure that accumulates a certain amount
              of rays/hits/iterations with one or more processes. A simulation
              can be canceled or finish gracefully. Status files in the 
              simulation results folder indicate that state of a simulation.
              Only one simulation for a given FCStd file can run at a time.
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

from numpy import *
import time
import datetime
import functools
import subprocess
import os
import sys
import threading
import signal
import itertools
import traceback
import tracemalloc

from ...detect_pyside import *
from ... import freecad_elements
from ... import io
from .. import results_store
from .. import tracing_cache
from . import worker_process

# fail gently if gui_windows module cannot imported
try:
  from ... import gui_windows
except Exception:
  gui_windows = None  


_TRACEMALLOC_INTERVAL = 60*60
_IS_MASTER_PROCESS = None
_SIMULATING_DOCUMENT = None
_BACKGROUND_PROCESSES = []
_ASSUME_DEAD_TIMEOUT = 15

# process info
def isMasterProcess():
  return _IS_MASTER_PROCESS

def setupJupyterMaster(path):
  '''
  Call this with a path to a FCStd file or results folder to make multiprocessing
  logic aware that this process is a jupyter process. 
  '''
  global _IS_MASTER_PROCESS
  _IS_MASTER_PROCESS = True
  # complain if already registered
  if io.isRegisteredJupyter():
    io.warn(f'setting jupyter master state even though already in jupyter master state '
            f'(this may imply a stale FreecadDocument handle is open somewhere)')
  # replace FCStd suffix
  if path.endswith('.FCStd'):
    path = path[:-6]+'.OpticsDesign'
  io.registerJupyterLogDir(path)

def jupyterBecomeSlave():
  '''
  Call this to change the role of this process to slave (e.g. when jupyter starts
  another process that will behave as a master)
  '''
  global _IS_MASTER_PROCESS
  if not io.isRegisteredJupyter():
    io.err(f'cannot use jupyterBecomeSlave if setupJupyterMaster was not called in advance')
  else:
    _IS_MASTER_PROCESS = False
    io.verb('becoming slave...')

def jupyterBecomeMaster():
  '''
  Call this to change the role of this process to master (e.g. when jupyter has
  started another process that behaved as a master, and that process finished)
  '''
  global _IS_MASTER_PROCESS
  if not io.isRegisteredJupyter():
    io.err(f'cannot use jupyterBecomeMaster if setupJupyterMaster was not called in advance')
  else:
    _IS_MASTER_PROCESS = True
    io.verb('becoming master...')

def unsetJupyterMaster():
  '''
  Call this to reset the role of this process for multiprocessing logic 
  to 'unknown'.
  '''
  global _IS_MASTER_PROCESS
  _IS_MASTER_PROCESS = None
  io.unregisterJupyterLogDir()

def isWorkerRunning():
  #print(isCanceled(), [w.isRunning() for w in _BACKGROUND_PROCESSES])
  _BACKGROUND_PROCESSES[:] = [w for w in _BACKGROUND_PROCESSES if w.isRunning()]
  return len(_BACKGROUND_PROCESSES)

def simulatingDocument():
  if _SIMULATING_DOCUMENT is not None:
    return _SIMULATING_DOCUMENT
  return App.activeDocument()

# status file info/manipulation
def _statusFilePath(name):
  return f'{results_store.getResultsFolderPath()}/{name}'

def _queryStatus(name):
  return os.path.exists(_statusFilePath(name))

def _setStatus(name, status):
  path = _statusFilePath(name)
  currentStatus = _queryStatus(name)
  if status and not currentStatus:    
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as _:
      pass
  elif not status and currentStatus:
    os.remove(path)

def isRunning():
  # if is-running file does not exist, case is closed
  if not _queryStatus('simulation-is-running'):
    return False

  # if is canceled file does not exist or a running
  # worker is known to us, assume we are still running
  if not isCanceled() or isWorkerRunning():
    return True

  # if cancel file and running file both exist and not a single worker is
  # known to this freecad process, assume run has ended without proper cleanup
  try:
    runningSince = os.stat(_statusFilePath('simulation-is-canceled')).st_mtime
    if time.time()-runningSince > _ASSUME_DEAD_TIMEOUT:
      io.warn(f'simulation was canceled {time.time()-runningSince:.1e}s ago but '
              f'is-running file still exists, assuming it died without proper '
              f'clean-up')
      setIsRunning(False)
      return False
  except Exception:
    pass

  # return true if none if the above applies  
  return True


def setIsRunning(state):
  return _setStatus('simulation-is-running', state)

def isCanceled():
  if status := _queryStatus('simulation-is-canceled'):
    try:
      setIsFinished(False)
    except Exception:
      pass
  return status

def setIsCanceled(state):
  _setStatus('simulation-is-canceled', state)

def cancelSimulation():
  if isRunning():
    setIsCanceled(True)

def isFinished():
  if status := _queryStatus('simulation-is-done'):
    try:
      setIsCanceled(False)
    except Exception:
      pass
  return status

def setIsFinished(state):
  _setStatus('simulation-is-done', state)


def runAction(action):
  '''
  This function is intended to be called by the GUI buttons and handles
  all possible actions that the buttons can trigger.
  '''
  # commands that start some sort of simulation:
  if action in ('fans', 'singlepseudo', 'singletrue', 'pseudo', 'true'):
    # simulation loop
    runSimulation(action)

  # stop button to cancel running simulation
  elif action == 'stop':
    io.info('canceling simulation...')
    cancelSimulation()


def runSimulation(action, slaveInfo={}):
  '''
  This function runs the actual work of a ray-tracing simulation and is 
  called either directly from the GUI thread or by the background worker
  processes. It keeps the GUI response using the "QApplication.processEvents"-hack
  but blocks until the simulation is done. 

  action: one of true, singletrue, pseudo, singlepseudo or fans, to determine
          how to generate rays
  slaveInfo: None if called from the master, dictionary with info passed
             from calling master process if called in a worker process
  '''
  # set global variable to mark whether we are slave or master
  global _IS_MASTER_PROCESS, _SIMULATING_DOCUMENT
  _IS_MASTER_PROCESS = not bool(slaveInfo)
  t0 = time.time()

  # reset bound box cache to prevent outdated stuff from prevailing
  tracing_cache.cacheClear()

  # setup random seeds to ensure good randomness across all workers and threads
  setupRandomSeed()

  store = None
  iteration = 0
  try:
    ##########################################################################################
    # prepare simulation, assemble simulation parameters from the various sources (settings,
    # defaults, mutual conditions, ...)

    # save active document and recompute
    _SIMULATING_DOCUMENT = App.activeDocument()
    _SIMULATING_DOCUMENT.recompute()

    # make sure other simulations have stopped and no other simulation
    # can be started
    if isMasterProcess():
      if isRunning():
        raise RuntimeError('another simulation seems to be running (or was just running and '
                           'exited ungently, in that case just retry in a few seconds)')
      setIsRunning(True)
      setIsCanceled(False)
      setIsFinished(False)
    
    # slaves expect simulation running state
    else:
      if not isRunning():
        raise RuntimeError('slave was launched but no simulation seems to be running')
        
    # determine simulation mode
    mode = action
    continuous = True
    if action.startswith('single'):
      mode = action[6:]
      continuous = False
    if action == 'fans':
      continuous = False
    
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

    # always disable drawing in slave processes
    if not isMasterProcess():
      draw = False

    # determine number if workers to spawn (single for single shot simulations, 
    # according to settings for more than one iteration)
    workers = 1
    if continuous and (settings := freecad_elements.find.activeSimulationSettings()):
      if settings.WorkerProcessCount == 'num_cpus':
        workers = cpuCount()
      else:
        workers = int(settings.WorkerProcessCount)

    # find limits if any to stop simulation
    endAfterIterations = 10
    endAfterRays = inf
    endAfterHits = inf
    if settings := freecad_elements.find.activeSimulationSettings():
      _parse = lambda x: int(round(float(x))) if x!='inf' else inf
      endAfterIterations = _parse(settings.EndAfterIterations)
      endAfterRays = _parse(settings.EndAfterRays)
      endAfterHits = _parse(settings.EndAfterHits)

    # generate simulation run folder name
    simulationRunFolder = slaveInfo.get('simulationRunFolder', 
                                        results_store.generateSimulationFolderName())

    # generate store object and open a gui window for it (if this is not run by worker)
    if store:
      store = results_store.SimulationResults(simulationType=mode, simulationRunFolder=simulationRunFolder,
                                              endAfterIterations=endAfterIterations, 
                                              endAfterRays=endAfterRays, endAfterHits=endAfterHits)
      
      # connect progress window to this store if more than one iteration is requested
      if isMasterProcess() and continuous and gui_windows:
        gui_windows.showProgressWindow(store)

    ##########################################################################################
    # do pre-worker launched init and post-worker launched init of each light source
    # and optical object

    # run pre-worker-launch init
    if isMasterProcess():
      io.verb(f'doing pre-worker-launch init of all components...')
      for obj in itertools.chain(freecad_elements.find.lightSources(), 
                                 freecad_elements.find.relevantOpticalObjects()):
        obj.Proxy.onInitializeSimulation(obj=obj, state='pre-worker-launch', ident='master')

    # launch background worker processes (one less than specified if draw is true because 
    # then the master process will also do work), only launch if we are the master process
    if isMasterProcess():
      if draw:
        backgroundWorkers = workers-1
        io.info(f'doing simulation work with {backgroundWorkers} background workers + 1 worker running in gui process')
      else:
        backgroundWorkers = workers
        io.info(f'doing simulation work with {backgroundWorkers} background workers and lazy gui process')

      # If background workers will be started, save document so they will work on the exact
      # state of the project, but make sure to save only if GUI exists, otherwise all 
      # ViewProvider objects will break and loose their info. 
      # This implies that a master running in headless mode
      # will not save before spawning the workers (which implies nothing must be can changed 
      # in the document in headless mode)
      if backgroundWorkers > 0 and App.GuiUp:
        io.verb(f'saving document {App.GuiUp=}')
        _SIMULATING_DOCUMENT.save()
      else:
        io.verb(f'skip saving document {App.GuiUp=}')

      # actually launch workers
      for workerNo in range(backgroundWorkers):
        _BACKGROUND_PROCESSES.append(worker_process.WorkerProcess(simulationType=mode, simulationRunFolder=simulationRunFolder))
        freecad_elements.keepGuiResponsiveAndRaiseIfSimulationDone()

    # doing post-worker-launch init
    io.verb(f'doing post-worker-lauch init of all components...')
    for obj in itertools.chain(freecad_elements.find.lightSources(), 
                                freecad_elements.find.relevantOpticalObjects()):
      obj.Proxy.onInitializeSimulation(obj=obj, state='post-worker-launch', ident='master' if isMasterProcess() else 'worker')

    # report to shell that simulation starts
    if isMasterProcess():
      io.info(f'starting simulation {mode=}, {store=}, {draw=}, {workers=}, {continuous=}')

    ##########################################################################################
    # mainloop A: run actual simulation work if we are a background worker or the master
    #             with draw=True
    if not isMasterProcess() or draw:
      if isMasterProcess():
        io.verb(f'gui process is not lazy and runs the simulation mainloop')
      
      # start memory profiling
      if isfinite(_TRACEMALLOC_INTERVAL):
        tracemalloc.start()
        lastTracemallocReport = time.time()

      while True:
        # do ray-tracing for all light sources
        lightSourceExists = False
        for obj in freecad_elements.find.lightSources():
          lightSourceExists = True

          # run iteration for the light source
          obj.Proxy.runSimulationIteration(obj=obj, mode=mode, draw=draw, store=store)

          # raise simulation canceled exception if parent PID is not alive
          if not isMasterProcess():
            try:
              os.kill(slaveInfo['parentPid'], 0)
            except OSError:
              raise RuntimeError(f'parent pid {slaveInfo["parentPid"]} seems to have died, exiting as well...')

          # handle GUI events and raise if simulation is done
          freecad_elements.keepGuiResponsiveAndRaiseIfSimulationDone()

          # log top 10 biggest memory allocations
          if time.time()-lastTracemallocReport > _TRACEMALLOC_INTERVAL:
            lastTracemallocReport = time.time()
            io.verb('tracemalloc: top 10 memory allocations')
            _snapshot = tracemalloc.take_snapshot()
            _top_stats = _snapshot.statistics('lineno')
            for _stat in _top_stats[:10]:
              io.verb(f'  > {_stat}')
        
        # make sure simulation is canceled if not light source exists
        if not lightSourceExists:
          io.err(f'no light source exists in current project, cannot trace any rays.')
          raise freecad_elements.SimulationEnded()

        if store:
          # tell storage object that iteration is done
          store.incrementIterationCount()

          # makes sure disk writes are happening (without this line no progress would be written
          # to disk in the rare case of no .addRay or .addRayHit calls at all during simulation)
          store.writeDiskIfNeeded()

          if isMasterProcess():
            # make sure progress is updated in master process (this will also trigger 
            # place finished file if one of the specified end criteria is reached)
            store.getProgress()

        # end mainloop after first iteration if not in continuous (=singleshot) mode      
        if not continuous:
          raise freecad_elements.SimulationEnded()
 
      # this point should never be reached under normal conditions
      raise RuntimeError('simulation loop ended unexpectedly')

    ##########################################################################################
    # mainloop B: do not do simulation work if we are the master and draw is False, just
    #             poll progress instead, do not use a loop, but a QTimer
    io.verb(f'gui process is lazy and just tracks progress')

    timer = QTimer()
    def updateProgress():
      if store and isMasterProcess():
        # make sure progress is updated (this will also place cancel/done files if one 
        # of the specified end criteria is reached)
        store.getProgress()

      # stop if canceled or done
      if isFinished():
        io.verb('simulation is done, exiting mainloop...')
        timer.stop()

      # stop if run was canceled
      if isCanceled():
        io.info('simulation is canceled, exiting mainloop...')
        timer.stop()

    timer.timeout.connect(updateProgress)
    timer.start(300)

    # this busy-loop makes the timer useless, but it is needed because cleanup is done
    # in the finally block. Maybe restructure this in the future to improve performance
    while isWorkerRunning():
      time.sleep(1e-2)
      freecad_elements.keepGuiResponsive()

  ##########################################################################################
  # SimulationEnded exception is silently ignored
  except freecad_elements.SimulationEnded:
    pass

  # any other error cancels simulation and is re-raised
  except Exception:
    setIsCanceled(True)
    io.err(traceback.format_exc())
    raise

  # cleanup after simulation loop finishes
  finally:
    # flush store if existing
    if store and hasattr(store, 'flush'):
      store.flush()

    # worker processes just exit, master process waits until all workers
    # are finished and then sets flag files 
    if isMasterProcess():
      # set is finished flag
      if not isCanceled():
        setIsFinished(True)

      # wait for workers to finish
      _t0 = time.time()
      lastPrint = time.time()
      while isWorkerRunning():

        # keep GUI responsive and limit loop speed
        time.sleep(1e-2)
        freecad_elements.keepGuiResponsive()

        # quit/kill worker processes if they take too long
        if time.time()-_t0 > 3:
          for w in _BACKGROUND_PROCESSES:
            if time.time()-_t0 < 7:
              w.quit()
            elif time.time()-_t0 < 10:
              w.terminate()
            else:
              w.kill()

        # report progress
        if time.time()-lastPrint > 3:
          io.info(f'waiting for {len(_BACKGROUND_PROCESSES)} worker processes to finish...')
          lastPrint = time.time()

      # make sure all logfiles of worker processes are collected and merged into main log
      io.gatherSlaveFiles()

      # run simulation exit hooks
      io.verb(f'running simulation-exit hook of all components...')
      for obj in itertools.chain(freecad_elements.find.lightSources(), 
                                 freecad_elements.find.relevantOpticalObjects()):
        obj.Proxy.onExitSimulation(obj=obj, ident='master' if isMasterProcess() else 'worker')

      # reset simulating document global reference
      _SIMULATING_DOCUMENT = None

      # remove is running flag
      setIsRunning(False)

      # clean temp files if existing
      if store:
        store.cleanup()

      # report success
      performanceDescription = ''
      if store and hasattr(store, 'performanceDescription'):
        performanceDescription = f' ({store.performanceDescription()})'
      io.info(f'simulation {"ended gracefully" if not isCanceled() else "was canceled"} '
              f'after {time.time()-t0:.1e}s{performanceDescription}')


@functools.cache
def cpuCount():
  '''
  Get number of physical cpus on this machine. Tries to parse lscpu output
  and falls back to os module functions if that fails. 
  '''
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


def setupRandomSeed():
  # setup random seeds for numpy's and python's random module to something
  # that will differ between processes and threads for good Monte-Carlo
  # performance
  import random
  import numpy.random
  random.seed(int(abs(os.getpid()*(time.time()%1)*threading.get_ident()+1000) % 2**32))
  numpy.random.seed(int(abs(os.getpid()*(time.time()%1)*threading.get_ident()+1000) % 2**32))
