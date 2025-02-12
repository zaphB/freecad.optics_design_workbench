from numpy import *
from matplotlib.pyplot import *
import seaborn as sns
import pandas as pd
import matplotlib.ticker
import seaborn as sns
import scipy.optimize

import threading
import time
import traceback
import functools
import multiprocessing
import pickle
from atomicwrites import atomic_write

from .. import io
from . import freecad_document
from . import progress

CLOSE_FREECAD_TIMEOUT = 30
_ALL_SWEEPERS = []

def closeAllSweepers():
  for s in _ALL_SWEEPERS:
    s.close()

@functools.cache
def _mpCtx():
  # use safest method='spawn' even if it is rather slow, but SweeperWorkers
  # will live many minutes usually, so the overhead does not matter
  return multiprocessing.get_context('spawn')

class SweeperOptimizeWorker:
  def __init__(self, sweeper, optimizeArgs):
    self._optimizeArgs = optimizeArgs
    self._sweeperInstance = sweeper

    # setup history dump path and randomize historyDumpInterval to
    # avoid synchronization
    self._optimizeArgs['historyDumpPath'] = self.historyDumpPath()
    self._optimizeArgs['historyDumpInterval'] = 30+30*random.random()

    # make sure background worker will never plot anything on his own
    self._optimizeArgs['progressPlotInterval'] = inf

    # set run in fresh copy to true to prevent any worker from every
    # touching the main FCStd file
    self._optimizeArgs['openFreshCopy'] = True

    # set path to dump history to
    self._historyDumpPath = os.path.realpath(f'temp-optimize-hist-{int(time.time()*1e3)}-{int(random.random()*1e5)}-pid{os.getpid()}-thread{threading.get_ident()}.pkl')

    # make sure sweeper sweeper document is closed to avoid inheriting
    # the opened FreecadDocument attributes to the child process
    self._sweeperInstance.close()

    # setup history attrs
    self._history = []

    # setup and start child process
    self._process = _mpCtx().Process(target=self._work)
    self._process.start()

  def historyDumpPath(self):
    return self._historyDumpPath

  def fetchHistory(self):
    # try to load history to update cached history
    try:
      with open(self.historyDumpPath, 'rb') as f:
        self._history = pickle.load(f)
      os.remove(self.historyDumpPath)
    except Exception:
      pass

    # return history
    return self._history

  def isRunning(self):
    return self._process.is_alive()

  def terminate(self):
    return self._process.terminate()

  def kill(self):
    return self._process.kill()

  def _work(self):
    self._sweeperInstance.optimize(**self._optimizeArgs)


class ParameterSweeper:
  '''
  The parameter sweeper allows to conveniently set/get/sweep/optimize 
  parameters in the freecad files using given names, instead of the 
  lengthy descriptions in the document tree.

  Arguments:

  getParameterFunc : function
    Define how named parameters are mapped to nodes in the freecad document. 
    The function has to accept one parameter, the FreecadDocument instance and
    is expected to return a dictionary. Keys in the returned dictionary are
    the sweepable parameter names, values of the dictionary are the 
    FreecadDocument parameter nodes.
    The odd indirect definition through as a function is necessary, because
    reopening the freecad file requires to rebuilt the references to freecad
    objects.
  '''
  def __init__(self, getParametersFunc, freecadDocumentKwargs={}):
    self._getParametersFunc = getParametersFunc
    self._freecadDocumentKwargs = freecadDocumentKwargs
    self._freecadDocument = None
    self._freecadDocumentLock = threading.RLock()
    self._closeDocumentAfterInactivityThread = None
    self._bounds = {}
    self._optimizeStepsArgCache = {}

  def _closeOnInactivity(self):
    while self._freecadDocument:
      if time.time()-self._freecadDocument.lastInteractionTime() > CLOSE_FREECAD_TIMEOUT:
        self.close()
        break
      # limit loop speed
      time.sleep(1/3)

  def __del__(self):
    self.close()

  def close(self):
    with self._freecadDocumentLock:
      try:
        if self._freecadDocument:
          self._freecadDocument.close()
      except BrokenPipeError:
        pass
      self._freecadDocument = None

      # remove self from global list
      _ALL_SWEEPERS[:] = [s for s in _ALL_SWEEPERS if s != self]

      # clear parameter cache if file was closed
      self.parameters.cache_clear()

  def open(self):
    with self._freecadDocumentLock:
      if self._freecadDocument is None:
        # append self to global sweeper list
        _ALL_SWEEPERS.append(self)

        # create instance and open freecad document
        self._freecadDocument = freecad_document.FreecadDocument(**self._freecadDocumentKwargs)
        self._freecadDocument.open()

        # silence simulation progress tracker
        progress.silenceProgressTracker()

        # clear parameter cache after newly opened file
        self.parameters.cache_clear()

        # setup background thread that closes document after some inactivity
        self._closeDocumentAfterInactivityThread = threading.Thread(target=self._closeOnInactivity)
        self._closeDocumentAfterInactivityThread.start()

  def freecadDocument(self):
    with self._freecadDocumentLock:
      self.open()
      return self._freecadDocument
  
  def _parameterNodeDict(self):
    with self._freecadDocumentLock:
      self.open()
      res = self._getParametersFunc(self._freecadDocument)
      if not len(res):
        raise ValueError(f'getParametersFunc return empty dict, a ParameterSweeper '
                         f'without parameters is pointless')
      return res

  @functools.cache
  def parameters(self):
    with self._freecadDocumentLock:
      return {k: v.get() for k,v in self._parameterNodeDict().items()}

  def set(self, **kwargs):
    with self._freecadDocumentLock:
      paramDict = self._parameterNodeDict()

      # check whether keys are valid
      for setKey in kwargs.keys():
        if setKey not in paramDict.keys():
          raise ValueError(f'parameter {setKey} does not exist in dictionary returned '
                           f'by the getParametersFunc used to create this sweeper.')

      # update parameter values
      for setKey, setVal in kwargs.items():
        # update value
        paramDict[setKey].set(setVal)

        # ensure value was set correctly
        success = False
        gotVal = paramDict[setKey].get()
        try:
          if isclose(setVal, gotVal):
            success = True
        except Exception:
          success = (setVal == gotVal)
        if not success:
          raise ValueError(f'try to set parameter {setKey} to value '
                           f'{repr(setVal)}, but got value {repr(gotVal)}.')

      # clear parameter cache if parameters were updated
      self.parameters.cache_clear()

  def setBounds(self, **kwargs):
    paramNames = self.parameters().keys()
    # make sure keys exist and bounds are well formed
    for k, v in kwargs.items():
      if k not in paramNames:
        raise ValueError(f'parameter with name {k} does not exist, '
                         f'expect one of: {", ".join(paramNames)}')
      try:
        lower, upper = sorted(list(v))
      except Exception:
        raise ValueError(f'found illegal bounds for parameter {k}: {v}, '
                         f'bounds must tuple of two numbers')
    
    # set bounds
    for k, v in kwargs.items():
      self._bounds[k] = sorted(list(v))

  def bounds(self):
    return {k: self._bounds.get(k, (-inf, inf)) for k in self.parameters().keys()}

  def optimizeStrategyStep(*args, relWaitForParallel=1/3, progressPlotInterval=30):
    '''
    Pass one or more dictionaries with optimize args to run
    optimization steps with varied free parameters, methods, etc. in parallel

    Passing dictionaries only will cause a sequence of optimize-calls with parameters
    given by the dictionary. All dictionaries inherit keys from prededing arg-dict.
    Only changed keys need to be specified. The following example will run one optimize
    with default method and the remaining args given in the first dict. The second 
    optimize run will use the same arguments as the first, except for method='evolution'. 
    
    optimizer.optimizeStrategyStep(
      dict(method=None, minimizeFunc=...),
    )
    optimizer.optimizeStrategyStep(
      dict(method='evolution') 
    )

    If a list of dictionaries is passed instead of a dictionary, two optimize calls
    will be run in parallel. Again later dicts in the list inherit from previous dicts.
    The following example will first run the default method and a Nelder-Mead optimizer
    in parallel. After one of them finished, we will wait relWaitForParallel*runtime 
    for the other optimize run and then proceed with a method=evolution run, which itself
    will start with the best result obtained before:

    optimizer.optimizeStrategyStep(
      dict(method=None, minimizeFunc=...),
      dict(method='Nelder-Mead') 
    )
    optimizer.optimizeStrategyStep(
      dict(method='evolution') 
    )
    '''
    # check validity of strategy
    if not len(args):
      raise ValueError('no steps for optimization strategy given')

    # add cache contents to all arg dicts
    for kwargs in args:
      self._optimizeStepsArgCache.update(kwargs)
      kwargs.update(self._optimizeStepsArgCache)

    # do work in this process, no workers launched
    if len(args) == 1:
      io.verb(f'running single process optimize with kwargs={args[0]}')
      self.optimize(**args[0])

    # launch workers to do work, this process just monitors
    else:
      io.verb(f'running multi process optimize with args={args}')
      t0 = time.time()
      lastProgressPlot = 0

      # create worker objects
      workers = []
      for kwargs in args:
        workers.append(SweeperOptimizeWorker(self, kwargs))

      bestParamsDict = None
      try:
        # monitor workers until happy
        lastWorkerFinished = None
        runningWorkers = []
        bestPenalty = inf
        lastPenaltyImprovement = 0
        tryToEndWorkersSince = inf
        while True:
          # fetch history of all worker progresses
          allParamsHist = []
          for w in workers:
            allParamsHist.extend(w.fetchHistory())
          allParamsHist = sorted(allParamsHist, key=lambda e: e[0])

          # check if global best-penalty improved
          if (_newBest:=min([h[1] for h in allParamsHist])) < bestPenalty:
            bestPenalty = _newBest
            lastPenaltyImprovement = time.time()
            bestParamsDict = allParamsHist[argmin([h[1] for h in allParamsHist])][4]

          # plot history of optimization and hits of best result so far
          if len(allParamsHist) > 5 and time.time()-lastProgressPlot > progressPlotInterval:
            lastProgressPlot = time.time()
            progress.clearCellOutput()

            fig, (ax1, ax2) = subplots(1, 2, figsize=(9,4))
            sca(ax1)
            sns.scatterplot(pd.DataFrame([p[:3] for p in allParamsHist]), x=0, y=1, 
                            style=2, size=2, markers=['.', '*'], sizes=[15, 40], legend=False,
                                        ).set(xlabel='time', ylabel='penalty')
            gca().xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                                              lambda x, p: io.secondsToStr(x-t0, length=1) ))
            gca().set_title(f'penalty history', fontsize=10) 

            # plot hits
            sca(ax2)
            bestResultSoFar = freecad_document.RawFolder(allParamsHist[argmin([h[1] for h in allParamsHist])][3])
            bestResultSoFar.loadHits('*').plot(*(['fanIndex', 'fan #'] if simulationMode=='fans' else []))
            gca().set_title(f'best result so far', fontsize=10)
            tight_layout()
            show()

            # print status
            io.info(f'optimize strategy step running since {io.secondsToStr(time.time()-t0)}')

          # update running workers list
          for w in runningWorkers:
            if not w.isRunning():
              lastWorkerFinished = time.time()
          runningWorkers = [w for w in runningWorkers if w.isRunning()]

          # end loop if all workers finished
          if not len(runningWorkers):
            break

          # if at least one worker finished and none of the other workers managed
          # to improve the penalty since relWaitForParallel*runtime, exit all remaining
          # workers
          if ( time.time()-lastWorkerFinished > relWaitForParallel*(lastWorkerFinished-t0)
                and time.time()-lastPenaltyImprovement > relWaitForParallel*(lastWorkerFinished-t0) ):
            tryToEndWorkersSince = time.time()
          
          # send kill/terminate signals depending on wait time
          if time.time()-tryToEndWorkersSince > 10:
            for w in runningWorkers:
              w.kill()
          elif time.time()-tryToEndWorkersSince > 0:
            for w in runningWorkers:
              w.terminate()

          # limit loop speed
          time.sleep(3)
        
      # make sure to apply best result to current FCStd file if loop ends
      finally:
        if bestParamsDict:
          self.set(bestParamsDict)


  def optimize(self, minimizeFunc, parameters, simulationMode, 
               prepareSimulation=None, simulationKwargs={},
               minimizeKwargs={}, progressPlotInterval=30, 
               method=None, historyDumpPath=None, 
               historyDumpInterval=inf, **kwargs):

    # setup progress and timing vars
    t0 = time.time()
    lastProgressPlot = 0
    lastHistoryDump = time.time()
    minimizeFuncHist = []
    allParamsHist = []
    bestPenaltySoFar, bestParametersSoFar, bestResultSoFar = inf, None, None

    parameters = list(parameters)
    with self._freecadDocumentLock:
      self.open()

      # wrap minimize func, run simulation before and pass additional args
      def _simulateAndMinimizeFunc(args):
        nonlocal bestPenaltySoFar, bestParametersSoFar, bestResultSoFar, lastProgressPlot

        # retry up to five times if exception is raised in the loop
        for retryNo in range(999):
          try:
            # call prepare simulation if given
            if prepareSimulation:
              prepareSimulation(self._freecadDocument, **kwargs)

            # set current parameters
            paramDict = {k: v for k,v in zip(parameters, args)}
            self.set(**paramDict)

            # run simulation and fetch result
            resultFolder = self._freecadDocument.runSimulation(simulationMode, **simulationKwargs)

            # plot progress (do this before the call to minimize func to make sure any output of minimize 
            # func will be visible below the progress info)
            if time.time()-lastProgressPlot > progressPlotInterval and len(allParamsHist) > 5:
              lastProgressPlot = time.time()
              progress.clearCellOutput()

              # plot history of optimization and hits of best result so far
              fig, (ax1, ax2) = subplots(1, 2, figsize=(9,4))
              sca(ax1)
              sns.scatterplot(pd.DataFrame([p[:3] for p in allParamsHist]), x=0, y=1, 
                              style=2, size=2, markers=['.', '*'], sizes=[15, 40], legend=False,
                                          ).set(xlabel='time', ylabel='penalty')
              gca().xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                                                lambda x, p: io.secondsToStr(x-t0, length=1) ))
              gca().set_title(f'penalty history', fontsize=10) 

              # plot hits
              sca(ax2)
              bestResultSoFar.loadHits('*').plot(*(['fanIndex', 'fan #'] if simulationMode=='fans' else []))
              gca().set_title(f'best result so far', fontsize=10) 
              tight_layout()
              show()

              # print status
              io.info(f'optimizer running since {io.secondsToStr(time.time()-t0)}')

            # calculate penalty
            penalty = minimizeFunc(resultFolder)

            # update history lists and shorten if necessary
            if penalty < bestPenaltySoFar:
              io.verb(f'found new optimum: {penalty=}, {paramDict=}')
              allParamsHist.append([time.time(), penalty, True, 
                                    os.path.realpath(resultFolder.path()), paramDict])
              bestParametersSoFar = dict(paramDict)
              bestPenaltySoFar = penalty
              bestResultSoFar = resultFolder
            else:
              allParamsHist.append([time.time(), penalty, False, 
                                    os.path.realpath(resultFolder.path()), paramDict])
            if len(allParamsHist) > 1e3:
              allParamsHist[:] = allParamsHist[::2]
            
            # dump entire history to file if enabled
            if historyDumpPath:
              if time.time()-lastHistoryDump > historyDumpInterval:
                lastHistoryDump = time.time()
                with atomic_write(historyDumpPath, mode='wb', overwrite=True) as f:
                  pickle.dump(allParamsHist, f)

            # return the penalty value
            return penalty

          # retry if something in the minimize function evaluation failed
          except Exception:
            if retryNo >= 5:
              raise
            elif retryNo >= 2:
              io.warn(f'exception raised during optimize, restart freecad slave, sleep and retry... ({retryNo=}):\n\n'+traceback.format_exc())
              self.close()
              time.sleep(10)
              self.open()
              time.sleep(3)
            else:
              io.warn(f'exception raised during optimize, gonna sleep and retry... ({retryNo=}):\n\n'+traceback.format_exc())
              time.sleep(3)

      # pass wrapped function to minimizer
      x0 = [self.parameters()[p] for p in parameters] 
      bounds = [self.bounds().get(p, (-inf, inf)) for p in parameters]
      io.info(f'starting optimizer with {minimizeFunc=}, {parameters=}, {simulationMode=}, '
              f'{simulationKwargs=}, {kwargs=}, {x0=}, {bounds=}')

      # run actual minimizer
      try:
        if method == 'annealing':
          return scipy.optimize.dual_annealing(_simulateAndMinimizeFunc, x0=x0, bounds=bounds, **minimizeKwargs) 
        elif method == 'evolution':
          return scipy.optimize.differential_evolution(_simulateAndMinimizeFunc, x0=x0, bounds=bounds, **minimizeKwargs) 
        if method:
          minimizeKwargs['method'] = method
        return scipy.optimize.minimize(_simulateAndMinimizeFunc, x0=x0, bounds=bounds, **minimizeKwargs) 

      # before returning, make sure parameters for global optimum are set
      finally:
        if bestParametersSoFar:
          self.set(**bestParametersSoFar)
