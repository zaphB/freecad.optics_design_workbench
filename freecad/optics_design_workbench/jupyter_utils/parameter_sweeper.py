'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *
from matplotlib.pyplot import *
import seaborn as sns
import pandas as pd
import matplotlib.ticker
import seaborn as sns
import scipy.optimize

import os
import threading
import time
import traceback
import functools
import multiprocessing
import pickle
import cloudpickle
import copy
from atomicwrites import atomic_write

from .. import io
from . import freecad_document
from . import progress
from . import retries

CLOSE_FREECAD_TIMEOUT = 90
_ALL_OPEN_SWEEPERS = []


def closeAllSweepers():
  for s in _ALL_OPEN_SWEEPERS:
    s.close()


@functools.cache
def _mpCtx():
  # use safest method='spawn' even if it is rather slow, but SweeperWorkers
  # will live many minutes usually, so the overhead does not matter
  return multiprocessing.get_context('forkserver')


def _unpickleAndWork(pickledSweeperOptimizeWorker, freecadExecutable):
  '''
  wrapper around SweeperOptimizeWorker._work method that is 
  a suitable multiprocessing.Process target
  '''
  freecad_document.setDefaultFreecadExecutable(freecadExecutable)
  _self = pickle.loads(pickledSweeperOptimizeWorker)
  _self.work()


class SweeperOptimizeWorker:
  def __init__(self, sweeper, optimizeArgs):
    self._lastSentTerminate = 0
    self._lastSentKill = 0
    self._termSignalInterval = 3
    self._killSignalInterval = 3
    self._tryToEndWorkersSince = None
    self._optimizeArgs = optimizeArgs

    # set path to dump history to
    self._historyDumpPath = os.path.abspath(f'{sweeper.resultsPath()}/tmp/optimize-hist-{int(time.time()*1e3)}-{int(random.random()*1e5)}-pid{os.getpid()}-thread{threading.get_ident()}.pkl')

    # setup history dump path and randomize historyDumpInterval to
    # avoid synchronization
    self._optimizeArgs['historyDumpPath'] = self.historyDumpPath()
    self._optimizeArgs['historyDumpInterval'] = 30+30*random.random()

    # make sure background worker will never plot anything on his own
    # self._optimizeArgs['progressPlotInterval'] = inf

    # setup history attrs
    self._history = []

    # Make sure sweeper sweeper document is closed to avoid inheriting
    # the opened FreecadDocument attributes to the child process.
    # Also remove the threading lock object, which cannot be passed to 
    # the child process (lock will be recreated next time it is needed)
    self._sweeperInstance = sweeper
    self._sweeperInstance.close()
    self._sweeperInstance._freecadLock = None

    # Pickle sweeper instance and optimize args func using cloudpickle,
    # because they are usually defined in a jupyter notebook.
    # The multiprocessing module uses built-in pickle and will not be able
    # to pass functions defined in the jupyter notebook to its workers. 
    pickledSelf = cloudpickle.dumps(self)

    # setup and start child process
    self._process = _mpCtx().Process(
                        target=_unpickleAndWork, 
                        args=(pickledSelf, 
                              freecad_document._DEFAULT_FREECAD_EXECUTABLE), 
                        daemon=True ) # <- kill process after parent has exited

  def start(self):
    self._process.start()

  def work(self):
    # make sure run-in-fresh-copy-mode is enabled to prevent any worker
    # from ever touching the main FCStd file
    self._sweeperInstance.setOpenFreshCopyMode(True)

    # run optimizer work
    self._sweeperInstance.optimize(**self._optimizeArgs)

  def historyDumpPath(self):
    return self._historyDumpPath

  def fetchHistory(self):
    # try to load history to update cached history
    try:
      if os.path.exists(self.historyDumpPath()):
        with open(self.historyDumpPath(), 'rb') as f:
          self._history = pickle.load(f)
        os.remove(self.historyDumpPath())
    except Exception:      
      io.verb(f'fetching history from {self.historyDumpPath()} '
              f'failed:\n\n'+traceback.format_exc())
    # return history
    return self._history

  def isRunning(self):
    return self._process.is_alive()

  def terminate(self):
    # limit signal send frequency
    if time.time()-self._lastSentTerminate > self._termSignalInterval:
      self._lastSentTerminate = time.time()
      self._termSignalInterval += 1
      io.verb(f'sent terminate signal to {self}')
      return self._process.terminate()

  def kill(self):
    # limit signal send frequency
    if time.time()-self._lastSentKill > self._killSignalInterval:
      self._killSignalInterval += 1
      self._lastSentKill = time.time()
      io.verb(f'sent kill signal to {self}')
      return self._process.kill()

  def escalatingQuit(self):
    if self._tryToEndWorkersSince is None:
      self._tryToEndWorkersSince = time.time()
    if time.time()-self._tryToEndWorkersSince > 15:
      self.kill()
    else:
      self.terminate()


class MetaParameter:
  '''
  This class implements set and get methods like the FreeCAD document
  parameters do. The get method returns the value previously set, or 
  nan if no set command was issued so far. The set command stores the
  set value and tries to set the dependent real parameters.
  '''
  def __init__(self, name, metaParameterFunc, sweeper):
    self._metaParameterFunc = metaParameterFunc
    self._name = name
    self._sweeper = sweeper
    self._siblings = [self]
    self._latestResultDict = {}
    self._value = nan
    self._allSiblingsWereSetOnce = False

  def setSiblings(self, siblings):
    self._siblings = list(siblings)

  def set(self, value, dontApplyMetaParamYet=False, **kwargs):
    # store whether value was nan before and update our own value
    wasNan = isnan(self._value)
    self._value = value

    # check if all siblings have non-nan value
    unsetSiblings = [p._name for p in self._siblings if isnan(p.get())]
    if not len(unsetSiblings):
      # report if this is the first time we reach this point and actually use the metaParameterFunc
      if not self._allSiblingsWereSetOnce:
        io.verb(f'meta parameter family {", ".join([p._name for p in self._siblings])} is '
                f'completely initialized and active from now on')
      self._allSiblingsWereSetOnce = True

      # calculate result dict to be set according to stored metaParameterFunc
      resultDict = self._metaParameterFunc(self._sweeper, **{p._name: p.get() for p in self._siblings})

      # set result dict in all siblings, sweeper.set will internally 
      if dontApplyMetaParamYet:
        self._latestResultDict = resultDict
        for s in self._siblings:
          s._latestResultDict = resultDict

      # alternatively: directly apply new result dict
      else:
        self._sweeper.set(**resultDict)

    # if other meta param siblings have not been set yet and our previous value was
    # non-nan, issue a warning
    else:
      if not wasNan:
        io.warn(f'set meta parameter {self._name} to {value}, but its the siblings '
                f'{", ".join(unsetSiblings)} have not been set yet. Setting meta '
                f'parameters only has an effect once all siblings have been set once.')


  def get(self):
    return self._value


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
    # close all open sweepers when a new one is created to prevent
    # to make life in jupyter notebooks easier
    while len(_ALL_OPEN_SWEEPERS):
      _ALL_OPEN_SWEEPERS[0].close()

    self._getParametersFunc = getParametersFunc
    self._metaParameterDict = {}
    self._freecadDocumentKwargs = freecadDocumentKwargs
    self._freecadDocument = None
    self._closeDocumentAfterInactivityThread = None
    self._freecadLock = None
    self._bounds = {}
    self._optimizeStepsArgCache = {}
  
  def addMetaParameters(self, metaParameterFunc):
    newMetaParams = {}
    for argName in list(inspect.signature(metaParameterFunc).parameters.keys())[1:]:
      if argName in list(self.parameters().keys()):
        raise ValueError(f'meta parameter function argument {repr(argName)} '
                         f'conflicts with existing parameter. Did you already '
                         f'add these metaparameters? Or does the name exist '
                         f'among the regular parameters?')

      # add meta parameter object to the dictionary
      newMetaParams[argName] = MetaParameter(argName, metaParameterFunc, self)

    # let all newly generated meta params know about their siblings
    for v in newMetaParams.values():
      v.setSiblings(newMetaParams.values())

    # save new meta params to dictionary
    self._metaParameterDict.update(newMetaParams)
    io.verb(f'registered meta parameters {newMetaParams}')
    
    # reset self.parameters cache to make sure meta params appear on next call
    self.parameters.cache_clear()

  def _freecadDocumentLock(self):
    if self._freecadLock is None:
      self._freecadLock = threading.RLock()
    return self._freecadLock

  def _closeOnInactivity(self):
    while self._freecadDocument:
      if time.time()-self._freecadDocument.lastInteractionTime() > CLOSE_FREECAD_TIMEOUT:
        self.close()
        break
      # limit loop speed
      time.sleep(1/3)

  def save(self):
    with self._freecadDocumentLock():
      if self._freecadDocument:
        self._freecadDocument.save()

  def __del__(self):
    self.close()

  def close(self):
    with self._freecadDocumentLock():
      try:
        if self._freecadDocument:
          self._freecadDocument.close()
      except BrokenPipeError:
        pass
      self._freecadDocument = None

      # remove self from global list
      _ALL_OPEN_SWEEPERS[:] = [s for s in _ALL_OPEN_SWEEPERS if s != self]

      # clear parameter cache if file was closed
      self.parameters.cache_clear()

      # remove reference to background thread (it will end on its 
      # own soon, because we set _freecadDocument to None)
      self._closeDocumentAfterInactivityThread = None

  def setOpenFreshCopyMode(self, mode):
    # close file if mode changed to ensure it is re-opened with proper mode
    # on next occasion
    prevMode = self._freecadDocumentKwargs.get('openFreshCopy', None)
    if prevMode != mode:
      self.resultsPath.cache_clear()
      self.close()

    # update freecad document kwargs
    self._freecadDocumentKwargs['openFreshCopy'] = mode

  def getOpenFreshCopyMode(self):
    return self._freecadDocumentKwargs.get('openFreshCopy', None)

  def open(self):
    with self._freecadDocumentLock():
      if self._freecadDocument is None or not self._freecadDocument.isRunning():
        # append self to global sweeper list
        _ALL_OPEN_SWEEPERS.append(self)

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
    with self._freecadDocumentLock():
      self.open()
      return self._freecadDocument

  @functools.cache
  def resultsPath(self):
    return self.freecadDocument().resultsPath()

  def _parameterNodeDict(self):
    with self._freecadDocumentLock():
      self.open()
      res = self._getParametersFunc(self._freecadDocument)
      res.update(self._metaParameterDict)
      if not len(res):
        raise ValueError(f'getParametersFunc return empty dict, a ParameterSweeper '
                         f'without parameters is pointless')
      return res

  @functools.cache
  def parameters(self):
    with self._freecadDocumentLock():
      return {k: v.get() for k,v in self._parameterNodeDict().items()}

  def set(self, **kwargs):
    with self._freecadDocumentLock():
      boundsDict = self.bounds()
      paramDict = self._parameterNodeDict()

      # check whether keys are valid
      for setKey in kwargs.keys():
        if setKey not in paramDict.keys():
          raise ValueError(f'parameter {setKey} does not exist in dictionary returned '
                           f'by the getParametersFunc used to create this sweeper.')

      # update parameter values
      for setKey, setVal in kwargs.items():
        # restrict set val if bounds are exceeded
        b1, b2 = boundsDict[setKey]
        if setVal < b1:
          io.warn(f'trying to set parameter {setKey} to {setVal}, which is below '
                  f'lower bound {b1}. Setting to lower bound {b1} instead.')
          setVal = b1
        if setVal > b2:
          io.warn(f'trying to set parameter {setKey} to {setVal}, which is above '
                  f'upper bound {b2}. Setting to upper bound {b2} instead.')
          setVal = b2

        # update value but dont apply meta params right away 
        paramDict[setKey].set(setVal, dontApplyMetaParamYet=True)

        # ensure value was set correctly
        success = False
        gotVal = paramDict[setKey].get()
        try:
          if isclose(setVal, gotVal, rtol=1e-3):
            success = True
        except Exception:
          success = (setVal == gotVal)
        if not success:
          raise ValueError(f'try to set parameter {setKey} to value '
                           f'{repr(setVal)}, but got value {repr(gotVal)}.')
      
      # apply all changed meta params, make sure to only apply one of each
      # sibling group to avoid many redundant calls
      appliedMetaParams = []
      for setKey, setVal in kwargs.items():
        param = paramDict[setKey]
        if isinstance(param, MetaParameter) and param not in appliedMetaParams:
          appliedMetaParams.append(param)
          appliedMetaParams.extend(param._siblings)
          self.set(**param._latestResultDict)

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

  def optimizeStrategyBegin(self):
    self._optimizeStepsArgCache = {}
    self._optimizeStepsPosArgCache = {}

  def optimizeStrategyStep(self, *args, 
                           progressCallback=None, 
                           relWaitForParallel=None, 
                           absWaitForParallel=None, 
                           progressPlotInterval=None,
                           saveInterval=None):
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
    global CLOSE_FREECAD_TIMEOUT

    # Cache positional argument values, too. Assume Nones mean parameter was not given
    self._optimizeStepsPosArgCache.update({k:v for k,v in locals().items() if k not in ('self', 'args') and v is not None})
    progressCallback = self._optimizeStepsPosArgCache.get('progressCallback', None)
    relWaitForParallel = self._optimizeStepsPosArgCache.get('relWaitForParallel', .5)
    absWaitForParallel = self._optimizeStepsPosArgCache.get('absWaitForParallel', 300)
    progressPlotInterval = self._optimizeStepsPosArgCache.get('progressPlotInterval', 60)
    saveInterval = self._optimizeStepsPosArgCache.get('saveInterval', 5*60)

    # add cache contents to all arg dicts
    for kwargs in args:
      self._optimizeStepsArgCache.update(kwargs)
      kwargs.update(self._optimizeStepsArgCache)

    # check validity of strategy
    if not len(args):
      raise ValueError('no steps for optimization strategy given')

    # do work in this process, no workers launched
    if len(args) == 1:
      io.verb(f'running single process optimize with kwargs={args[0]}')
      self.optimize(**args[0])

    # launch workers to do work, this process just monitors
    else:
      io.verb(f'running multi process optimize with args={args}')
      t0 = time.time()
      lastProgressPlot = 0

      # increase freecad timeout duration to a very log time to avoid annoying reopenings
      # during optimize strategy
      CLOSE_FREECAD_TIMEOUT = 3600
      
      # save document and create worker objects
      self.save()
      workers = []
      io.verb(f'setting up worker processes...')
      for kwargs in args:
        workers.append(SweeperOptimizeWorker(self, kwargs))
      
      # start worker processes (do creation of workers and starting in separate loops to avoid
      # stretching the period of worker launch induced window flickering for too long)
      io.verb(f'launching worker processes...')
      for w in workers:
        # sleep random time between worker creation to avoid stressing the filesystem unnecessarily
        time.sleep(.2+.2*random.random())
        w.start()

      bestParamsDict = None
      bestParamsArgs = None
      try:
        # monitor workers until happy
        lastWorkerFinished = inf
        runningWorkers = list(workers)
        bestPenalty = inf
        lastPenaltyImprovement = 0
        tryToEndWorkersSince = inf
        lastDocumentSave = time.time()
        while True:

          # fetch history of all worker progresses
          allParamsHist = []
          for w in workers:
            allParamsHist.extend(w.fetchHistory())
          allParamsHist = sorted(allParamsHist, key=lambda e: e[0])
          while len(allParamsHist) > 1e4:
            allParamsHist = allParamsHist[::2]

          # check if global best-penalty improved
          if len(allParamsHist) and (_newBest:=min([h[1] for h in allParamsHist])) < bestPenalty:
            bestPenalty = _newBest
            lastPenaltyImprovement = time.time()
            _best = allParamsHist[argmin([h[1] for h in allParamsHist])]
            bestParamsDict = _best[4]
            bestParamsArgs = _best[5]
            io.verb(f'found new best solution {bestPenalty=},\n{bestParamsDict=}\n{bestParamsArgs=}')
            _b = self.bounds()
            _paramsRelToBounds = {k: (v-_b[k][0])/(_b[k][1]-_b[k][0]) 
                                           for k,v in bestParamsDict.items()}
            io.verb(f'params in best solution that are close to bounds: '
                    f'{[k for k,v in _paramsRelToBounds.items() if isclose(v, 0, atol=1e-3) or isclose(v, 1, atol=1e-3)]} '
                    f'(all params renormalized to bounds: {_paramsRelToBounds})')

          # update non-temp document every now and then with best params so far and 
          # save to disk to avoid losing all on a crash
          if time.time()-lastDocumentSave > saveInterval:
            lastDocumentSave = time.time()
            io.verb('autosaving current best result')
            self.set(**bestParamsDict)
            self.save()

          # plot history of optimization and hits of best result so far
          if len(allParamsHist) > 15 and time.time()-lastProgressPlot > progressPlotInterval:
            lastProgressPlot = time.time()
            progress.clearCellOutput()

            fig, ax1 = subplots(1, 1, figsize=(6,4))
            sca(ax1)
            sns.scatterplot(pd.DataFrame([p[:3] for p in allParamsHist]), x=0, y=1, 
                            style=2, size=2, markers=['.', '*'], sizes=[15, 40], legend=False,
                                        ).set(xlabel='time', ylabel='penalty')
            _allFinitePenalties = [p[1] for p in allParamsHist if isfinite(p[1])]
            if len(_allFinitePenalties) > 50:
              l, u = min(_allFinitePenalties), quantile(_allFinitePenalties, .5)
              if min(_allFinitePenalties) > 0 and u/l > 30:
                ax1.semilogy()
                ax1.set_ylim([l / (u/l)**0.05, u * (u/l)**0.5])
              else:
                ax1.set_ylim([l-.05*(u-l), u+0.5*(u-l)])
            ax1.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                                              lambda x, p: io.secondsToStr(x-t0, length=1) ))
            ax1.set_title(f'penalty history ({len(runningWorkers)}/{len(workers)} workers busy)', fontsize=10)

            # save plot to disk
            savefig(f'{self.resultsPath()}/optimize-progress.pdf')

            # show plot in notebook
            show()

            # close figure
            close()

            # print status
            io.info(f'optimize strategy step running since {io.secondsToStr(time.time()-t0)}, {len(runningWorkers)}/{len(workers)} workers busy')

            # run custom progress callback if given
            if progressCallback:
              progressCallback(bestParams=bestParamsDict, history=allParamsHist)
            lastProgressPlot = time.time()

          # update running workers list
          for w in runningWorkers:
            if not w.isRunning():
              io.verb(f'worker {w} finished')
              lastWorkerFinished = time.time()
          runningWorkers = [w for w in runningWorkers if w.isRunning()]

          # end loop if all workers finished
          if not len(runningWorkers):
            io.verb(f'all workers finished, exiting...')
            break

          # if at least one worker finished and none of the other workers managed
          # to improve the penalty since relWaitForParallel*runtime, exit all remaining
          # workers
          if ( not isfinite(tryToEndWorkersSince)
               and time.time()-lastWorkerFinished > relWaitForParallel*(lastWorkerFinished-t0)
                                                      + absWaitForParallel
               and time.time()-lastPenaltyImprovement > relWaitForParallel*(lastWorkerFinished-t0)
                                                          + absWaitForParallel ):
            io.verb(f'at least one worker finished '
                    f'({io.secondsToStr(time.time()-lastWorkerFinished)} ago) '
                    f'and others did not improve for more '
                    f'than {io.secondsToStr(relWaitForParallel*(lastWorkerFinished-t0))}, '
                    f'(last improvement {io.secondsToStr(time.time()-lastPenaltyImprovement)} ago) '
                    f'quitting remaining workers...')
            tryToEndWorkersSince = time.time()
          
          # send kill/terminate signals depending on wait time
          if time.time()-tryToEndWorkersSince > 0:
            for w in runningWorkers:
              w.escalatingQuit()

          # limit loop speed
          time.sleep(3)
        
      # make sure to apply best result to current FCStd file if loop ends
      finally:
        io.info(f'optimize strategy step ended, {bestParamsDict=}')
        if bestParamsDict:
          self.set(**bestParamsDict)
          self.save()

        # wait for all workers to finish
        lastPrint = time.time()
        while True:
          runningWorkers = [w for w in workers if w.isRunning()]
          if not len(runningWorkers):
            break
          if time.time()-lastPrint > 10:
            lastPrint = time.time()
            io.warn(f'optimize strategy step ended, but still waiting for {len(runningWorkers)} workers to exit...')

          # send kill/terminate signals depending on wait time
          for w in runningWorkers:
            w.escalatingQuit()

          # limit loop speed
          time.sleep(1/2)

        # make sure all progress files are cleared
        for w in workers:
          w.fetchHistory()

        # restore standard 90s freecad timeout
        CLOSE_FREECAD_TIMEOUT = 90

  def optimizeStrategyEnd(self):
    self._optimizeStepsArgCache = {}
    self.purgeTempFolder()
  

  def purgeTempFolder(self):
    self.freecadDocument().purgeTempFolder()


  def optimize(self, minimizeFunc, parameters, simulationMode, 
               prepareSimulation=None, simulationKwargs={},
               minimizerKwargs={}, progressPlotInterval=30, 
               method=None, historyDumpPath=None, 
               historyDumpInterval=inf, **kwargs):
    # save optimize params to variable
    optimizeParams = {k:v for k,v in locals().items() if k not in ('self',)}

    # setup progress and timing vars
    t0 = time.time()
    lastProgressPlot = 0
    lastHistoryDump = time.time()
    minimizeFuncHist = []
    allParamsHist = []
    bestPenaltySoFar, bestParametersSoFar, bestResultSoFar = inf, None, None

    parameters = list(parameters)
    with self._freecadDocumentLock():
      self.open()

      # wrap minimize func, run simulation before and pass additional args
      def _simulateAndCalcMinimizeFunc(args):
        nonlocal lastProgressPlot, lastHistoryDump
        nonlocal bestPenaltySoFar, bestParametersSoFar, bestResultSoFar

        # to enhance stability: if something raises an error during the function
        # evaluation, return a very large number
        try:
          # run prepare simulation-hook
          @retries.retryOnError(subject='preparing simulation')
          def _prepareSimulation():
            if prepareSimulation:
              prepareSimulation(self._freecadDocument, **kwargs)
          _prepareSimulation()

          # extract param dict from args, un-normalize parameters that have both bounds set
          _b = self.bounds()
          paramDict = {k: v*(_b[k][1]-_b[k][0])+_b[k][0] if all(isfinite(_b[k])) else v 
                                                          for k,v in zip(parameters, args)}

          # run simulation, if simulating fails, set penalty to very large number
          @retries.retryOnError(subject='setting parameters and running simulation',
                                maxRetries=4, callbackAfterRetries=2, callback=self.close)
          def _runSimulation():
            self.set(**paramDict)
            return self._freecadDocument.runSimulation(simulationMode, **simulationKwargs)
          resultFolder = _runSimulation()

          # plot progress if it is time (do this before the call to minimize func to make sure 
          # any output of minimize func will be visible below the progress info)
          if time.time()-lastProgressPlot > progressPlotInterval and len(allParamsHist) > 5:
            lastProgressPlot = time.time()
            progress.clearCellOutput()

            # plot history of optimization and hits of best result so far
            fig, ax1 = subplots(1, 1, figsize=(6,4))
            sca(ax1)
            sns.scatterplot(pd.DataFrame([p[:3] for p in allParamsHist]), x=0, y=1, 
                            style=2, size=2, markers=['.', '*'], sizes=[15, 40], legend=False,
                                        ).set(xlabel='time', ylabel='penalty')
            gca().xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                                              lambda x, p: io.secondsToStr(x-t0, length=1) ))
            gca().set_title(f'penalty history', fontsize=10) 

            # save plot to disk
            savefig(f'{self.resultsPath()}/optimize-progress.pdf')

            # show in notebook (if not running as worker)
            if not self.getOpenFreshCopyMode():
              show()

            # close figure
            close()

            # print status
            io.info(f'optimizer running since {io.secondsToStr(time.time()-t0)}')

          # calculate penalty
          @retries.retryOnError(subject='evaluating minimize func')
          def _calcPenalty():
            return minimizeFunc(resultFolder)
          penalty = _calcPenalty()

          # update history lists and shorten if necessary
          if penalty < bestPenaltySoFar:
            io.verb(f'found new optimum: {penalty=}, {paramDict=}')
            allParamsHist.append([time.time(), penalty, True, 
                                  os.path.realpath(resultFolder.path()), paramDict, 
                                  optimizeParams])
            bestParametersSoFar = dict(paramDict)
            bestPenaltySoFar = penalty
            bestResultSoFar = resultFolder
            _b = self.bounds()
            _paramsRelToBounds = {k: (v-_b[k][0])/(_b[k][1]-_b[k][0]) 
                                            for k,v in paramDict.items()}
            io.verb(f'params in best solution that are close to bounds: '
                    f'{[k for k,v in _paramsRelToBounds.items() if isclose(v, 0, atol=1e-3) or isclose(v, 1, atol=1e-3)]} '
                    f'(all params renormalized to bounds: {_paramsRelToBounds})')
          else:
            allParamsHist.append([time.time(), penalty, False, 
                                  os.path.realpath(resultFolder.path()), paramDict, 
                                  optimizeParams])
          while len(allParamsHist) > 1e4:
            allParamsHist[:] = allParamsHist[::2]
          
          # dump entire history to file if enabled
          if historyDumpPath:
            if time.time()-lastHistoryDump > historyDumpInterval:
              lastHistoryDump = time.time()
              try:
                os.makedirs(os.path.dirname(historyDumpPath), exist_ok=True)
                with atomic_write(historyDumpPath, mode='wb', overwrite=True) as f:
                  cloudpickle.dump(allParamsHist, f)
              except Exception:
                io.warn(f'dumping progress failed:\n\n'+traceback.format_exc())

          # return the penalty value
          return penalty

        # capture any exception, log the stack trace and return ridiculously large number
        except Exception:
          io.warn(f'exception was raised in optimizer iteration:\n\n'+traceback.format_exc())
          return 1e99

      # prepare arguments for minimizer: if params have both limits set, renormalize to (0,1) interval
      _b = self.bounds()
      _p = self.parameters()
      x0 = [(_p[k]-_b[k][0])/(_b[k][1]-_b[k][0]) if all(isfinite(_b[k])) else _p[k] for k in parameters]
      bounds = [[-.001,1.001] if all(isfinite(_b[k])) else _b[k] for k in parameters]
      io.info(f'starting optimizer with {method=} {minimizeFunc=}, {parameters=}, {simulationMode=}, '
              f'{simulationKwargs=}, {kwargs=}, {x0=}, {bounds=}')

      # run actual minimizer
      try:
        if method == 'annealing':
          return scipy.optimize.dual_annealing(_simulateAndCalcMinimizeFunc, x0=x0, bounds=bounds, **minimizerKwargs) 
        elif method == 'evolution':
          return scipy.optimize.differential_evolution(_simulateAndCalcMinimizeFunc, x0=x0, bounds=bounds, **minimizerKwargs) 
        if method:
          minimizerKwargs['method'] = method
        return scipy.optimize.minimize(_simulateAndCalcMinimizeFunc, x0=x0, bounds=bounds, **minimizerKwargs)

      # before returning, make sure parameters for global optimum are set
      finally:
        if bestParametersSoFar:
          self.set(**bestParametersSoFar)
          self.save()
