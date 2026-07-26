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
from .. import raytracing_cache
from . import worker_process

# fail gently if gui_windows module cannot imported
try:
  from ... import gui_windows
except Exception:
  gui_windows = None  

# set tracemalloc interval only for debugging purposes, never use in release builds
# because it (ironically) generates a significant memory consumption overhead
_TRACEMALLOC_INTERVAL = inf

_RESULT_CHUNKING_INTERVAL = 50*60
_IS_JUPYTER_CONTEXT = False
_IS_MASTER_PROCESS = None
_SIMULATING_DOCUMENT = None
_WORKER_PROCESSES = []
_ASSUME_DEAD_TIMEOUT = 15


#########################################################################################
# logic to set/unset jupyter master/slave states

def isMasterProcess():
  return _IS_MASTER_PROCESS

def setIsJupyterContext(state):
  global _IS_JUPYTER_CONTEXT
  _IS_JUPYTER_CONTEXT = state

def setupJupyterMaster(path):
  '''
  Call this with a path to a FCStd file or results folder to make multiprocessing
  logic aware that this process is a jupyter process. 
  '''
  global _IS_MASTER_PROCESS, _IS_JUPYTER_CONTEXT
  _IS_MASTER_PROCESS = True
  # complain if already registered
  if io.isRegisteredJupyter():
    io.warn(f'setting jupyter master state even though already in jupyter master state '
            f'(this may imply a stale FreecadDocument handle is open somewhere)')
  # replace FCStd suffix
  if path.endswith('.FCStd'):
    path = path[:-6]+'.OpticsDesign'
  io.registerJupyterLogDir(path)
  _IS_JUPYTER_CONTEXT = True

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
  global _IS_MASTER_PROCESS, _IS_JUPYTER_CONTEXT
  _IS_MASTER_PROCESS = None
  _IS_JUPYTER_CONTEXT = False
  io.unregisterJupyterLogDir()


#########################################################################################
# logic to find out which worker processes are running/busy and in which the current
# simulation is at the moment

def isWorkerRunning():
  for w in _WORKER_PROCESSES:
    if not w.isRunning():
      io.verb(f'worker {w} exited, clearing it from list')
  _WORKER_PROCESSES[:] = [w for w in _WORKER_PROCESSES if w.isRunning()]
  return len(_WORKER_PROCESSES)

def isWorkerBusy():
  return len([w for w in _WORKER_PROCESSES if w.isBusy()])

def ensureWorkerCount(workerCount):
  missingWorkers = (workerCount - isWorkerRunning())
  if missingWorkers > 0:
    io.verb(f'require {workerCount} worker processes but only {isWorkerRunning()} are alive '
            f'-> launching {missingWorkers} workers')
    for _ in range(missingWorkers):
      _WORKER_PROCESSES.append(worker_process.WorkerProcess(isJupyterContext=_IS_JUPYTER_CONTEXT))
  elif workerCount != isWorkerRunning():
    io.verb(f'require {workerCount} worker processes, {isWorkerRunning()} are already alive')

def cleanupUnneededWorkers():
  for w in _WORKER_PROCESSES:
    if time.time()-w.wasLastBusy > 10*60:
      _t0 = time.time()
      while w.isRunning():
        if time.time()-_t0 < 5:
          worker.quit()
        elif time.time()-_t0 < 10:
          worker.terminate()
        else:
          worker.kill()
        time.sleep(1e-2)

def simulatingDocument():
  if _SIMULATING_DOCUMENT is not None:
    return _SIMULATING_DOCUMENT
  return App.activeDocument()

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

def isRunning( attemptCleanup=True ):
  # if is-running file does not exist, case is closed
  if not _queryStatus('simulation-is-running'):
    return False

  # if is canceled file does not exist or a running
  # worker is known to us, assume we are still running
  if not isCanceled() or isWorkerBusy():
    return True

  # try to resolve inconsistent flag file stats after ungently killed simulations
  if attemptCleanup:
    # if cancel file and running file both exist and not a single worker is
    # known to this freecad process, assume run has ended without proper cleanup
    t0 = time.time()
    i = 0
    while True:
      # every 20th loop iteration check if is-canceled file is old enough to 
      # assume the process died
      i += 1
      if i%20==1:

        # check two regular criteria first before going on with cleanup attempt
        if not _queryStatus('simulation-is-running'):
          return False
        if not isCanceled() or isWorkerBusy():
          return True

        canceledAt = os.stat(_statusFilePath('simulation-is-canceled')).st_mtime
        if time.time()-canceledAt > _ASSUME_DEAD_TIMEOUT:
          io.warn(f'simulation was canceled {time.time()-canceledAt:.0f}s ago but '
                  f'is-running file still exists, assuming it died without proper '
                  f'clean-up')
          setIsRunning(False)
          return False

        # emit warning on very first iteration
        if i==1:
          io.warn(f'simulation was canceled {time.time()-canceledAt:.0f}s ago but '
                  f'is-running file still exists, waiting a while and rechecking...')

        # dont spend more time than ASSUME_DEAD_TIMEOUT +10% on checking this
        if time.time()-t0 > 1.1*_ASSUME_DEAD_TIMEOUT:
          break

      # keep gui response while polling
      freecad_elements.keepGuiResponsive()
      time.sleep(1e-2)
  
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
  if isRunning( attemptCleanup=False ):
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


#########################################################################################
# functions that run the actual simulation loops depending on role of the current process

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
  raytracing_cache.cacheClear()

  # setup random seeds to ensure good randomness across all workers and threads
  setupRandomSeed()

  store = None
  iteration = 0
  skipUpdateFlagFiles = False
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
        raise RuntimeError(f'another simulation seems to be running (or was just running '
                           f'and exited ungently, in that case press cancel and retry)')
      setIsRunning(True)
      setIsCanceled(False)
      setIsFinished(False)
    
    # slaves expect simulation running state
    else:
      if not isRunning():
        raise RuntimeError('slave simulation task was launched but no simulation seems to be running')
        
    # determine simulation mode
    mode = action
    continuous = True
    if action.startswith('single'):
      mode = action[6:]
      continuous = False
    if action == 'fans':
      continuous = False

    # always store if started from a jupyter context
    if _IS_JUPYTER_CONTEXT:
      store = True
    # determine whether to store results or not from the mode and settings
    if isMasterProcess():
      store = False
      storeSingleShot = False
      if settings := freecad_elements.find.activeSimulationSettings():
        storeSingleShot = settings.EnableStoreSingleShotData
      if action in ('singlepseudo', 'singletrue', 'fans'):
        store = storeSingleShot
      if action in ('pseudo', 'true'):
        store = True
    # always store if we are slave process (slaves will only be started if dumping
    # results to disks is intended)
    else:
      store = True

    # determine whether to draw rays or not
    draw = True
    drawContinuous = True
    if settings := freecad_elements.find.activeSimulationSettings():
      drawContinuous = settings.ShowRaysInContinuousMode
    if action in ('pseudo', 'true'):
      draw = drawContinuous

    # always disable drawing in slave processes and when launched from jupyter
    if not isMasterProcess() or _IS_JUPYTER_CONTEXT:
      draw = False

    # store flag for special cas fan simulation triggered by jupyter
    isMultiCoreFans = _IS_JUPYTER_CONTEXT and action == 'fans'
    if isMultiCoreFans:
      action = 'multicorefans'
      store = True # <- store has to be created to dump init condition files

    # determine number if workers to spawn (single for single shot simulations, 
    # according to settings for more than one iteration OR if fan simulation
    # triggered by jupyter and has to be calculated parallelized)
    workers = 1
    if continuous or isMultiCoreFans:
      workers = cpuCount()
      if settings := freecad_elements.find.activeSimulationSettings():
        if settings.WorkerProcessCount == 'num_cpus':
          workers = cpuCount()
        else:
          workers = int(settings.WorkerProcessCount)

    # find limits if any to stop simulation
    endAfterIterations = inf
    endAfterRays = 1e4
    endAfterHits = inf
    if settings := freecad_elements.find.activeSimulationSettings():
      _parse = lambda x: int(round(float(x))) if x!='inf' else inf
      endAfterIterations = _parse(settings.EndAfterIterations)
      endAfterRays = _parse(settings.EndAfterRays)
      endAfterHits = _parse(settings.EndAfterHits)
    # disable all cancel conditions in multicore fan mode
    if action == 'multicorefans':
      endAfterIterations = inf
      endAfterRays = inf
      endAfterHits = inf

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
      
      # let master process dump the global info once (transformation matrices etc)
      if isMasterProcess():
        # TODO: remove try except when function seems stable enough
        try:
          store.dumpGlobalInfo( freecad_elements.collectGlobalInfo() )
        except Exception:
          io.warn('failed to dump gobal info:')
          io.warn(traceback.format_exc())

    ##########################################################################################
    # do pre-worker launched init and post-worker launched init of each light source
    # and optical object

    # run pre-worker-launch init
    if isMasterProcess():
      io.verb(f'doing pre-worker-launch init of all components...')
      for obj in itertools.chain(freecad_elements.find.lightSources(), 
                                 freecad_elements.find.relevantOpticalObjects()):
        obj.Proxy._onInitializeSimulation(obj=obj, state='pre-worker-launch', ident='master')
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

      # make sure enough workers are alive
      ensureWorkerCount(backgroundWorkers)

      # make workers start their work
      for i in range(backgroundWorkers):
        _WORKER_PROCESSES[i].startSimulation(simulationType=mode, 
                                             simulationRunFolder=simulationRunFolder)
        freecad_elements.keepGuiResponsiveAndRaiseIfSimulationDone()

    # define function to ensure appropriate number of worker processes are busy
    def ensureWorkersAreBusy():
      # kill and restart workers after they reach their end-of-life that to 
      # circumvent memory leaks
      for worker in _WORKER_PROCESSES:
        if time.time() > worker.endOfLife:
          io.verb(f'killing worker {worker} that reached end of life...')
          _t0 = time.time()
          while worker.isRunning():
            if time.time()-_t0 < 7:
              worker.quit()
            elif time.time()-_t0 < 10:
              worker.terminate()
            else:
              worker.kill()
          break

      # ensure expected number of workers are busy
      ensureWorkerCount(backgroundWorkers)
      for i in range(backgroundWorkers):
        if not (p:=_WORKER_PROCESSES[i]).isBusy():
          # make sure to avoid starting work in un-busy workers if simulation is done
          # (minUpdateInteval to zero to enforce checking if simulation is done right now)
          freecad_elements.keepGuiResponsiveAndRaiseIfSimulationDone(minUpdateInterval=0)

          # let worker start simulation job
          io.verb(f'found worker #{p.index} not busy, starting simulation on this worker...')
          p.startSimulation(simulationType=mode, 
                            simulationRunFolder=simulationRunFolder)

    # doing post-worker-launch init
    io.verb(f'doing post-worker-launch init of all components...')
    for obj in itertools.chain(freecad_elements.find.lightSources(), 
                                freecad_elements.find.relevantOpticalObjects()):
      obj.Proxy.onInitializeSimulation(obj=obj, state='post-worker-launch', ident='master' if isMasterProcess() else 'worker')

    # report to shell that simulation starts
    if isMasterProcess():
      io.info(f'starting simulation {mode=}, {store=}, {draw=}, {workers=}, {continuous=}')
    
    #
    # TODO: completely rewrite the simulation mainloop logic: split generation of initial conditions for rays
    #       and ray tracing. Idea: master generates initial conditions, offers these to clients via zmq and 
    #       only do the ray tracing. Nothing is shared through files on disk anymore, only via zmq messaging.
    #       the master process is the only process that dumps results to disk from time to time.
    #       This will be a huge chunk of work, but the simulation_loop will look much cleaner because the slaved
    #       will have much less logic to handle. Cases with enabled/disabled drawing, single/multi processing,
    #       fans started by jupyter or not will all enter quite different branches of runSimulation, which is
    #       bad style. With zmq all the logic branching will be done by the master only, slaves just receive
    #       initial conditions for ray-tracing and do the tracing.  
    #       Plus, zmq can scale across multiple machines and easily switch transports. Jupyter is bases on 
    #       zmq anyways, therefore it is not even a new dependency.
    #       When rewriting all this the 'keepGuiResponsive()' hack can hopefully be abandoned, too.
    #

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

      lastResultChunking = time.time()

      while True:
        # do ray-tracing for all light sources
        lightSourceExists = False
        for obj in freecad_elements.find.lightSources():
          lightSourceExists = True

          # special case multicore-fans: do not use light sources own ray generator,
          # instead ask result store for rays
          useInitialConditions = None
          if action == 'multicorefans':
            if (initConditions:=store.consumeInitialCondition()) is None:
              raise freecad_elements.SimulationEnded()
            useInitialConditions = initConditions

          obj.Proxy.runSimulationIteration(obj=obj, mode=mode, draw=draw, store=store, 
                                           useInitialConditions=useInitialConditions)

          # raise simulation canceled exception if parent PID is not alive
          if not isMasterProcess():
            try:
              os.kill(slaveInfo['parentPid'], 0)
            except OSError:
              raise RuntimeError(f'parent pid {slaveInfo["parentPid"]} seems to have died, exiting as well...')

          # handle GUI events and raise if simulation is done
          if action != 'multicorefans':
            freecad_elements.keepGuiResponsiveAndRaiseIfSimulationDone()

          # log top 10 biggest memory allocations
          if isfinite(_TRACEMALLOC_INTERVAL):
            if time.time()-lastTracemallocReport > _TRACEMALLOC_INTERVAL:
              lastTracemallocReport = time.time()
              io.verb('tracemalloc: top 20 memory allocations')
              _snapshot = tracemalloc.take_snapshot()
              _top_stats = _snapshot.statistics('lineno')
              for _stat in _top_stats[:20]:
                io.verb(f'  > {_stat}')
        
        # make sure simulation is canceled if no light source exists
        if not lightSourceExists:
          io.err(f'no light source exists in current project, cannot trace any rays.')
          raise freecad_elements.SimulationEnded()

        if store:
          # tell storage object that iteration is done
          if action != 'multicorefans':
            store.incrementIterationCount()

          # makes sure disk writes are happening (without this line no progress would be written
          # to disk in the rare case of no .addRay or .addRayHit calls at all during simulation)
          store.writeDiskIfNeeded()

          if isMasterProcess():
            # make sure progress is updated in master process (this will also place the finished 
            # file if one of the specified end criteria is reached, disable this in case of 
            # multicorefans mode)
            store.getProgress()
        
            # chunk result files every hour to make loading the results faster later
            if time.time()-lastResultChunking > _RESULT_CHUNKING_INTERVAL:
              io.verb(f'chunking result files...')
              lastResultChunking = time.time()
              store.chunkFiles(updateGuiCallback=freecad_elements.keepGuiResponsive)

            # kill workers beyond their lifetime, restart died workers, etc
            ensureWorkersAreBusy()

        # keep GUI responsive and limit loop speed
        if action != 'multicorefans':
          time.sleep(1e-2)
          freecad_elements.keepGuiResponsiveAndRaiseIfSimulationDone()

        # end mainloop after first iteration if not in continuous (=singleshot) mode      
        if not continuous and action != 'multicorefans':
          raise freecad_elements.SimulationEnded()
 
      # this point should never be reached under normal conditions
      raise RuntimeError('simulation loop ended unexpectedly')

    ##########################################################################################
    # mainloop B: do not do simulation work if we are the master and draw is False, just
    #             poll progress instead, do not use a loop, but a QTimer
    io.verb(f'gui process is lazy and just tracks progress')
    lastResultChunking = time.time()

    # special case multi core fans: go through all light sources and fetch all initial conditions for rays
    rayInitialConditions = []
    if action == 'multicorefans':
      for obj in freecad_elements.find.lightSources():
        rayInitialConditions.extend( obj.Proxy.runSimulationIteration(obj=obj, mode=mode, returnInitialConditions=True) )
    chunkSize = min([ 50, max([ 1, len(rayInitialConditions)//30 ]) ])

    timer = QTimer()
    def updateProgress():
      nonlocal lastResultChunking, rayInitialConditions

      # a little bit of serious work is still needed in multicorefans -> we have to generate
      # all fan parameters and drop them to disk as soon as previous ones were consumed
      if action == 'multicorefans':
        if len(rayInitialConditions) > 0:
          jobFiles = store.listInitialConditions()
          while len(rayInitialConditions)>0 and (not jobFiles or len(jobFiles) < 100*backgroundWorkers):
            rayInitialConditions, _dump = rayInitialConditions[chunkSize:], rayInitialConditions[:chunkSize]
            #io.warn(f'dumping {len(_dump)} initial condition files to disk, {len(rayInitialConditions)} initial conditions left')
            # replace unpickleable attributes with suitable replacements
            for ray in _dump:
              ray.lightSource = ray.lightSource.Name
              ray.initPoint = (ray.initPoint.x, ray.initPoint.y, ray.initPoint.z)
              ray.initDirection = (ray.initDirection.x, ray.initDirection.y, ray.initDirection.z)
            store.dumpInitialConditions( _dump )
            jobFiles = store.listInitialConditions()
        else:
          timer.stop()

      if store and isMasterProcess():
        # make sure progress is updated (this will also place cancel/done files if one 
        # of the specified end criteria is reached)
        store.getProgress()

        # chunk result files every hour to make loading the results faster later
        if time.time()-lastResultChunking > _RESULT_CHUNKING_INTERVAL:
          io.verb(f'chunking result files...')
          lastResultChunking = time.time()
          store.chunkFiles(updateGuiCallback=freecad_elements.keepGuiResponsive)

        # kill workers beyond their lifetime, restart died workers, etc
        # (make sure not to raise SimulationEnded exception because this is running in a timer)
        # (disabled in action == 'multicorefans' mode)
        if action != 'multicorefans':
          try:
            ensureWorkersAreBusy()
          except Exception:
            pass

      # stop if canceled or done
      if action != 'multicorefans':
        if isFinished():
          io.verb('simulation is done, exiting mainloop...')
          timer.stop()

      # stop if run was canceled
      if isCanceled():
        io.info('simulation is canceled, exiting mainloop...')
        timer.stop()

    timer.timeout.connect(updateProgress)
    timer.start(300)

    # this busy-loop makes the timer useless, but it is needed because cleanup is done in
    # the finally block. Maybe restructure this in the future to improve GUI responsiveness
    while isWorkerBusy():
      time.sleep(1e-2)
      freecad_elements.keepGuiResponsive()

  ##########################################################################################
  # SimulationEnded exception is silently ignored
  except freecad_elements.SimulationEnded:
    pass

  # any other error cancels simulation and is re-raised
  except Exception as e:
    # only cancel if the exception was not related to another simulation still being busy
    if 'another simulation seems to be running' in str(e):
      # set flag to remember during cleanup not to set is-finished flag file 
      skipUpdateFlagFiles = True
    else:
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
      if not skipUpdateFlagFiles and not isCanceled():
        setIsFinished(True)

      # wait for workers to finish
      _t0 = time.time()
      lastPrint = time.time()
      while _busyCount:=isWorkerBusy():
        # report progress
        if time.time()-lastPrint > 3:
          io.info(f'waiting for {_busyCount} worker processes to finish...')
          lastPrint = time.time()

      # check which workers have not been used in a long time
      cleanupUnneededWorkers()

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
      if not skipUpdateFlagFiles:
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
