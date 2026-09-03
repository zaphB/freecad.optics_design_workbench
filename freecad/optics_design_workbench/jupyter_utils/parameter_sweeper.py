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


class OptimizationEnded(RuntimeError):
  pass


class SweeperOptimizeWorker:
  def __init__(self, sweeper, optimizeArgs):
    self._lastSentTerminate = 0
    self._lastSentKill = 0
    self._termSignalInterval = 3
    self._killSignalInterval = 3
    self._tryToEndWorkersSince = None
    self._optimizeArgs = optimizeArgs
    self._wasStarted = False

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
    # Also remove the threading lock object (and make sure to own it 
    # beforehand), which cannot be passed to the child process.
    # The lock will be recreated next time it is needed.
    with sweeper._freecadDocumentLock():
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
                                freecad_document._GET_FREECAD_EXECUTABLE()), 
                          daemon=True ) # <- kill process after parent has exited

  def freshClone(self):
    return SweeperOptimizeWorker(self._sweeperInstance, self._optimizeArgs)

  def start(self):
    self._wasStarted = True
    self._process.start()

  def work(self):
    # set close timeout to ridiculously large value for any worker, because
    # workers operate in workInTempCopy mode and re-opening the FCStd file
    # would restore the original version, erasing any optimization progress
    CLOSE_FREECAD_TIMEOUT = 1e6

    # make sure run-in-fresh-copy-mode is enabled to prevent any worker
    # from ever touching the main FCStd file
    self._sweeperInstance.setWorkInTempCopyMode(True)

    # run optimizer work
    self._sweeperInstance.optimize(**self._optimizeArgs)

  def historyDumpPath(self):
    return self._historyDumpPath

  def fetchHistory(self):
    # try to load history to update cached history
    try:
      if os.path.exists(self.historyDumpPath()):
        with open(self.historyDumpPath(), 'rb') as f:
          self._history = io.unpickle(f)
        os.remove(self.historyDumpPath())
    except Exception:      
      io.verb(f'fetching history from {self.historyDumpPath()} '
              f'failed:\n\n'+traceback.format_exc())
    # return history
    return self._history

  def wasStarted(self):
    return self._wasStarted

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
  The parameter sweeper allows to conveniently set/get/sweep/optimize parameters in the .FCStd files using handy short names instead of the lengthy descriptions document tree paths.

  Parameters
  ----------

  getParametersFunc : function
    Define how named parameters are mapped to nodes in the freecad document. 
    The function has to accept one parameter, the FreecadDocument instance and
    is expected to return a dictionary. Keys in the returned dictionary are
    the sweepable parameter names, values of the dictionary are the 
    FreecadDocument parameter nodes.
    The odd indirect definition through as a function is necessary, because
    reopening the freecad file requires to rebuilt the references to freecad
    objects.

  freecadDocumentKwargs : dict, optional
    Dictionary of keyword arguments that want to pass the the FreecadDocument
    object that the sweeper creates internally.
  '''
  def __init__(self, getParametersFunc, freecadDocumentKwargs={}):
    # close all open sweepers when a new one is created to prevent
    # to make life in jupyter notebooks easier
    while len(_ALL_OPEN_SWEEPERS):
      _ALL_OPEN_SWEEPERS[0].close()

    # skip error checks after setting params if they take more than 10% of total time
    self.maxRelErrorCheckingLoad = 0.1

    self._getParametersFunc = getParametersFunc
    self._metaParameterDict = {}
    self._freecadDocumentKwargs = freecadDocumentKwargs
    self._freecadDocument = None
    self._closeDocumentAfterInactivityThread = None
    self._freecadLock = None
    self._bounds = {}
    self._optimizeStepsArgCache = {}
    self._setOperationTotalDurations = [1]
    self._setOperationErrorCheckDurations = [0]
    self._lastSetParamTimeStatisticsReport = 0
  
  def addMetaParameters(self, metaParameterFunc):
    '''
    Register metaparameters, that is parameters that are not 1:1 corresponding to 
    FreeCAD model parameters.

    Parameters
    ----------

    metaParameterFunc : function
      Function that defines how to-be-added metaparameters are mapped to existing
      parameters. The first argument to the function is the FreecadDocument instance,
      every further argument is a new metaparameter. Argument names must not conflict
      with existing parameter names.
      The function must return a dictionary, each key of which corresponds to an
      existing parameter (or metaparameter).
      When a metaparameter is set using sweeper.set(...), the passed function will
      be called and the resulting dict will be passed to sweeper.set(...) recursively.
    '''
    newMetaParams = {}
    relevantArgs = list(inspect.signature(metaParameterFunc).parameters.keys())[1:]
    if not len(relevantArgs):
      raise ValueError(f'function ')
    for argName in relevantArgs:
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
    'Save FCStd file to disk.'
    with self._freecadDocumentLock():
      if self._freecadDocument:
        self._freecadDocument.save()

  def __del__(self):
    self.close()

  def close(self):
    'Close underlying FCStd file handle.'
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

  def setWorkInTempCopyMode(self, mode):
    '''
    Set whether this sweeper works on the original FCStd file or in a tmp copy.

    Parameters
    ----------

    mode : bool
      False -> work in live copy, True -> work in tmp copy.
    '''
    # close file if mode changed to ensure it is re-opened with proper mode
    # on next occasion
    prevMode = self._freecadDocumentKwargs.get('workInTempCopy', None)
    if prevMode != mode:
      self.resultsPath.cache_clear()
      self.close()

    # update freecad document kwargs
    self._freecadDocumentKwargs['workInTempCopy'] = mode

  def getWorkInTempCopyMode(self):
    '''
    Returns
    -------
    
    bool
      False -> this sweeper works on the original FCStd file, True -> this sweeper works in a tmp copy.
    '''
    return self._freecadDocumentKwargs.get('workInTempCopy', None)

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
    '''
    Returns
    -------
    
    FreecadDocument
      Document reference used by this sweeper.
    '''
    with self._freecadDocumentLock():
      self.open()
      return self._freecadDocument

  @functools.cache
  def resultsPath(self):
    '''
    Returns
    -------

    str
      Path at which this sweeper stores simulation results.
    '''
    return self.freecadDocument().resultsPath()

  def _parameterNodeDict(self):
    with self._freecadDocumentLock():
      res = self._getParametersFunc(self.freecadDocument())
      res.update(self._metaParameterDict)
      if not len(res):
        raise ValueError(f'getParametersFunc return empty dict, a ParameterSweeper '
                         f'without parameters is pointless')
      return res

  @functools.cache
  def parameters(self):
    '''
    Get dictionary of all parameters that this sweeper knows.

    Returns
    -------

    dict
      Dictionary of all parameters. Keys are (meta)parameter names, values are the respective parameter values.
      Metaparameter values cannot be deduced from the FCSTd document state, therefore any metaparameter will show
      up as *nan* in this dictionary if it has not been set before. If it has been set before, it will show up 
      as the last set value.
    '''
    with self._freecadDocumentLock():
      return {k: v.get() for k,v in self._parameterNodeDict().items()}

  def set(self, **kwargs):
    '''
    Update parameter values.

    Parameters
    ----------

    **kwargs : any
      Takes arbitrary number of parameters. Parameter names must be existing sweeper parameters or metaparameters.
      Values are the values to be set.
    '''
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
        t0setParam = time.time()
        
        # restrict set val if bounds are exceeded
        b1, b2 = boundsDict[setKey]
        try:
          setVal > b1
        except TypeError:
          # silently skip bounds checks if param value is not comparable (e.g. string)
          pass
        else:
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

        # ensure value was set correctly, but dont spend too much time on it
        recentTimeSpentSettingParams = sum(self._setOperationTotalDurations)
        recentTimeSpentErrorChecking = sum(self._setOperationErrorCheckDurations)
        if time.time()-self._lastSetParamTimeStatisticsReport > 60:
          self._lastSetParamTimeStatisticsReport = time.time()
          io.verb(f'{recentTimeSpentSettingParams=:.1f}, {recentTimeSpentErrorChecking=:.1f}')
        if recentTimeSpentErrorChecking < self.maxRelErrorCheckingLoad*recentTimeSpentSettingParams:
          t0errorCheck = time.time()
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
          self._setOperationErrorCheckDurations.append( time.time()-t0errorCheck )
        else:
          # store zero to keep 1:1 correspondence between total duration and error check duration log entries
          self._setOperationErrorCheckDurations.append( 0 )
        self._setOperationErrorCheckDurations = self._setOperationErrorCheckDurations[-100:]
        
        # store time spent setting this parameter
        self._setOperationTotalDurations.append( time.time()-t0setParam )
        self._setOperationTotalDurations = self._setOperationTotalDurations[-100:]
      
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
    '''
    Update parameter bounds.

    Parameters
    ----------

    **kwargs : any
      Takes arbitrary number of parameters. Parameter names must be existing sweeper parameters or metaparameters.
      Values have to be length two tuples (or similar) containing a lower and an upper limit.
    '''
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
    '''
    Returns
    -------
    
    dict
      Dictionary of all parameter bounds.
    '''
    return {k: self._bounds.get(k, (-inf, inf)) for k in self.parameters().keys()}

  def optimizeStrategyBegin(self, **kwargs):
    '''
    Has to be called before starting a multi-step optimization strategy.

    Parameters
    ----------

    **kwargs : any
      Any keyword argument passed to this method will be stored as a default
      value for every following optimize strategy step.
    '''
    self._optimizeStepsArgCache = {}
    self._optimizeStepsPosArgCache = kwargs

  def optimizeStrategyStep(self, *args, 
                           progressCallback=None, 
                           relWaitForParallel=None, 
                           absWaitForParallel=None, 
                           progressPlotInterval=None,
                           saveInterval=None,
                           maxWorkerReviveCount=None,
                           workerReviveDelay=None,):
    '''
    Run one or more optimizers in parallel. 

    Parameters
    ----------

    *args : dict
      Pass one or more dictionaries, dictionaries must be argument lists valid for :meth:`optimize`. 
      Each dictionary will start one parallel 
      self.optimize call. All dictionaries inherit keys from keys passed to self.optimizeStrategyBegin
      and from preceding dictionaries in *args.
      The following example will run one optimize with default method and the remaining args
      given in the first dict. The second optimize run will use the same arguments as the first, 
      except for method='evolution':
      
      >>> optimizer.optimizeStrategyStep(
            dict(minimizeFunc=...),
            dict(method='evolution') 
          )
    '''
    global CLOSE_FREECAD_TIMEOUT

    # cache positional argument values, too. Assume Nones mean parameter was not given
    if not hasattr(self, '_optimizeStepsPosArgCache'):
      self.optimizeStrategyBegin()
    self._optimizeStepsPosArgCache.update({k:v for k,v in locals().items() if k not in ('self', 'args') and v is not None})
    progressCallback = self._optimizeStepsPosArgCache.get('progressCallback', None)
    relWaitForParallel = self._optimizeStepsPosArgCache.get('relWaitForParallel', .5)
    absWaitForParallel = self._optimizeStepsPosArgCache.get('absWaitForParallel', 300)
    progressPlotInterval = self._optimizeStepsPosArgCache.get('progressPlotInterval', 60)
    saveInterval = self._optimizeStepsPosArgCache.get('saveInterval', 5*60)
    maxWorkerReviveCount = self._optimizeStepsPosArgCache.get('maxWorkerReviveCount', 3)
    workerReviveDelay = self._optimizeStepsPosArgCache.get('workerReviveDelay', 1800)
    endIfFuncBelow = self._optimizeStepsArgCache.get('endIfFuncBelow', -inf)

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
        workers[-1].restartCount = 0
      jobCount = len(workers)
      
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
        activeWorkers = list(workers)
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
          if time.time()-lastDocumentSave > saveInterval and bestParamsDict is not None:
            lastDocumentSave = time.time()
            io.verb('autosaving current best result')
            try:
              self.set(**bestParamsDict)
              self.save()
            except Exception:
              io.warn(f'trying to save best params so far to document raised exception:\n\n'+traceback.format_exc())
              self.close()

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
            ax1.set_title(f'minimizeFunc history ({len(activeWorkers)}/{jobCount} workers busy)', fontsize=10)

            # save plot to disk
            tight_layout()
            savefig(f'{self.resultsPath()}/optimize-progress.pdf')

            # show plot in notebook
            show()

            # close figure
            close()

            # print status
            io.info(f'optimize strategy step running since {io.secondsToStr(time.time()-t0)}, {len(activeWorkers)}/{len(workers)} workers busy')

            # run custom progress callback if given
            if progressCallback and bestParamsDict is not None:
              try:
                progressCallback(bestParams=bestParamsDict, history=allParamsHist)
              except Exception:
                io.warn(f'progressCallback raised exception:\n\n'+traceback.format_exc())
            lastProgressPlot = time.time()

          # update running workers list
          for i, w in enumerate(activeWorkers):
            if not w.isRunning() and w.wasStarted():
              io.verb(f'worker {w} finished (was restarted {w.restartCount} times so far)')
              lastWorkerFinished = time.time()

              # create fresh clone of finished worker if more than one other worker is still running
              # and if best penalty improved recently
              if (not getattr(w, 'wasCloned', False)
                  and w.restartCount < maxWorkerReviveCount
                  and len([w for w in activeWorkers if w.isRunning()]) > 1):

                # mark old worker as cloned
                w.wasCloned = True
                
                # create new worker object from finished one and append to lists
                newWorker = w.freshClone()
                newWorker.startAt = time.time()+workerReviveDelay
                newWorker.restartCount = w.restartCount + 1
                activeWorkers.append(newWorker)
                workers.append(newWorker)

          # start workers that have 'startAt' attribute set if their time has come
          for w in activeWorkers:
            if not w.wasStarted() and getattr(w, 'startAt', inf) > time.time():
              # try to save current best params to file, such that new worker will use latest params
              if bestParamsDict is not None:
                try:
                  self.set(**bestParamsDict)
                  self.save()
                except Exception:
                  io.warn(f'trying to save best params so far to document raised exception:\n\n'+traceback.format_exc())
                  self.close()
              # starting worker
              io.info(f'worker {w} was started (this is restart #{w.restartCount} of this job)')
              w.start()
          
          # keep only workers that are either running or are still waiting to be started
          activeWorkers = [w for w in activeWorkers if w.isRunning() or not w.wasStarted()]

          # end loop if all workers finished
          if not len(activeWorkers):
            io.verb(f'all workers finished, exiting...')
            break

          # check other exit criteria
          if not isfinite(tryToEndWorkersSince):

            # if at least one worker finished and none of the other workers managed to improve the 
            # penalty since relWaitForParallel*runtime, exit all remaining workers
            if (time.time()-lastWorkerFinished > relWaitForParallel*(lastWorkerFinished-t0)
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

            # if one worker managed to reach penalty below target exit all workers 
            if bestPenalty < endIfFuncBelow:
              io.verb(f'penalty reached target threshold {endIfFuncBelow=}, {bestPenalty=} '
                      f'(last improvement {io.secondsToStr(time.time()-lastPenaltyImprovement)} ago) '
                      f'quitting remaining workers...')
              tryToEndWorkersSince = time.time()

          # send kill/terminate signals depending on wait time
          if time.time()-tryToEndWorkersSince > 0:
            # remove workers that have not been started yet
            activeWorkers = [w for w in activeWorkers if w.isRunning() and w.wasStarted()]

            # send escalating quit commands to remaining workers
            for w in activeWorkers:
              w.escalatingQuit()

          # limit loop speed
          time.sleep(3)
        
      # make sure to apply best result to current FCStd file if loop ends
      finally:
        io.info(f'optimize strategy step ended, {bestParamsDict=}')
        if bestParamsDict:
          try:
            self.set(**bestParamsDict)
            self.save()
          except Exception:
            io.warn(f'trying to save best params so far to document raised exception:\n\n'+traceback.format_exc())
            self.close()

        # wait for all workers to finish
        lastPrint = time.time()
        while True:
          activeWorkers = [w for w in workers if w.isRunning()]
          if not len(activeWorkers):
            break
          if time.time()-lastPrint > 10:
            lastPrint = time.time()
            io.warn(f'optimize strategy step ended, but still waiting for {len(activeWorkers)} workers to exit...')

          # send kill/terminate signals depending on wait time
          for w in activeWorkers:
            w.escalatingQuit()

          # limit loop speed
          time.sleep(1/2)

        # make sure all progress files are cleared
        for w in workers:
          w.fetchHistory()

        # restore standard 90s freecad timeout
        CLOSE_FREECAD_TIMEOUT = 90

  def optimizeStrategyEnd(self):
    'Has to be called after a multi-step optimization strategy is finished.'
    self._optimizeStepsArgCache = {}
    self.purgeTempFolder()
  
  def purgeTempFolder(self):
    'Permanently delete all temp copies created in the current simulation project.'
    self.freecadDocument().purgeTempFolder()

  def runSimulation(self, simulationMode, paramDict=None, **kwargs):
    '''
    Run a ray-tracing simulation.

    Parameters
    ----------

    simulationMode : str
      Select ray-tracing simulation mode. Must be one of 'fans', 'true', 'pseudo'.

    paramDict : dict, optional
      Dictionary of parameter names and values to be set before the simulation starts.

    **kwargs : any
      Internally calls :meth:`FreecadDocument.runSimulation`, any further keyword arguments are forwarded.

    Returns
    -------

    :class:`FreecadDocument.RawFolder`
      Folder reference containing the simulation results.

    '''
    @retries.retryOnError(subject='setting parameters and running simulation',
                          maxRetries=4, callbackAfterRetries=2, callback=self.close)
    def _runSimulation():
      if paramDict is not None:
        self.set(**paramDict)
      with self._freecadDocumentLock():
        return self.freecadDocument().runSimulation(simulationMode, **kwargs)
    return _runSimulation()

  def optimize(self, minimizeFunc, parameters, simulationMode,
               prepareSimulation=None, simulationKwargs={},
               minimizerKwargs={}, progressPlotInterval=30, 
               method='Nelder-Mead', historyDumpPath=None, 
               historyDumpInterval=inf, 
               endIfFuncBelow=-inf,
               freecadRestartInterval=3*60*60, **kwargs):
    '''
    Run an optimizer.

    Parameters
    ----------

    minimizeFunc : func
      Function to minimize. Function must take exactly one argument, which is the 
      :func:`RawFolder` reference of a simulation run result.

    parameters : list
      List of strings specifying parameter names of this sweeper. The optimizer
      will vary all given parameters within allowed bounds to minimize 
      *minimizeFunc*.

    simulationMode : str
      Select ray-tracing simulation mode. Must be one of 'fans', 'true', 'pseudo'.

    endIfFuncBelow : float, optional
      If the optimizer finds a set of parameters for wich minimizeFunc yields a value
      smaller than this endIfFuncBelow, the optimization ends. Defaults to negative 
      infinity, i.e. the optimization ends only if the optimization algorithm finishes.

    method : str, optional
      Optimization method. See method argument of *scipy.optimize.minimize* for
      allowed values. Special cases: method='annealing' uses *scipy.optimize.dual_annealing*,
      method='evolution' uses *scipy.optimize.differential_evolution*.

    minimizerKwargs : dict, optional
      Specify custom keyword arguments passed to the internal calls to
      *scipy.optimize.minimize* (or *dual_annealing* or *differential_evolution*
      if method is set accordingly)

    prepareSimulation : func, optional
      Function to call before running simulations.

    simulationKwargs : dict, optional
      Specify custom keyword arguments passed to the internal calls to
      :meth:`FreecadDocument.runSimulation`.

    progressPlotInterval : float, optional
      Interval to wait between periodic progress plots in seconds.

    freecadRestartInterval : float, optional
      Interval to wait between periodic clean restarts of the FreeCAD subprocess. This
      ensures the file on disk is saved and cleanly reloaded from time to time.

    historyDumpPath : str, optional
      File path at which to dump entire history of parameters tried by the optimizer.
      Default is to not save full history.

    historyDumpInterval : float, optional
      Interval to wait between periodic history dumps in seconds.

    **kwargs : any
      Any further keyword arguments are passed to prepareSimulation, if enabled.
      This allows to select simulation settings directly from the argument
      dict, which is especially useful when using :meth:`.runOptimizeStrategyStep`.

    Returns
    -------

      optimizationResult
        optimization result returned by *scipy.optimize.minimize* (or *dual_annealing* 
        or *differential_evolution* if method is set accordingly). Warning: anything
        related to parameter values, such as the vector *.x* of this object, are using
        units rescaled to the parameters bounds.
    '''
    # save optimize params to variable
    optimizeParams = {k:v for k,v in locals().items() if k not in ('self',)}

    # setup progress and timing vars
    t0 = time.time()
    lastProgressPlot = 0
    lastFreecadRestart = time.time()
    lastHistoryDump = time.time()
    minimizeFuncHist = []
    allParamsHist = []
    bestPenaltySoFar, bestParametersSoFar, bestResultSoFar = inf, None, None

    parameters = list(parameters)
    with self._freecadDocumentLock():

      # wrap minimize func, run simulation before and pass additional args
      def _simulateAndCalcMinimizeFunc(args):
        nonlocal lastProgressPlot, lastHistoryDump
        nonlocal bestPenaltySoFar, bestParametersSoFar, bestResultSoFar
        nonlocal lastFreecadRestart

        # to enhance stability: if something raises an error during the function
        # evaluation, return a very large number
        try:
          # run prepare simulation-hook
          @retries.retryOnError(subject='preparing simulation')
          def _prepareSimulation():
            if prepareSimulation:
              with self._freecadDocumentLock():
                prepareSimulation(self.freecadDocument(), **kwargs)
          _prepareSimulation()

          # extract param dict from args, un-normalize parameters that have both bounds set
          _b = self.bounds()
          paramDict = {k: v*(_b[k][1]-_b[k][0])+_b[k][0] if all(isfinite(_b[k])) else v 
                                                          for k,v in zip(parameters, args)}
          resultFolder = self.runSimulation(simulationMode, paramDict=paramDict, **simulationKwargs)

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
                                        ).set(xlabel='time', ylabel='minimizeFunc value')
            gca().xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                                              lambda x, p: io.secondsToStr(x-t0, length=1) ))
            gca().set_title(f'minimizeFunc history', fontsize=10) 
            _allFinitePenalties = [p[1] for p in allParamsHist if isfinite(p[1])]
            if len(_allFinitePenalties) > 50:
              l, u = min(_allFinitePenalties), quantile(_allFinitePenalties, .5)
              if min(_allFinitePenalties) > 0 and u/l > 30:
                ax1.semilogy()
                ax1.set_ylim([l / (u/l)**0.05, u * (u/l)**0.5])
              else:
                ax1.set_ylim([l-.05*(u-l), u+0.5*(u-l)])

            # save plot to disk
            savefig(f'{self.resultsPath()}/optimize-progress.pdf')

            # show in notebook (if not running as worker)
            if not self.getWorkInTempCopyMode():
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
            io.verb(f'found new optimum: {minimizeFunc=}, {paramDict=}')
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
            if ( time.time()-lastHistoryDump > historyDumpInterval
                  or penalty < endIfFuncBelow ): # <- immediately dump if penalty is below exit-thresh
              lastHistoryDump = time.time()
              try:
                os.makedirs(os.path.dirname(historyDumpPath), exist_ok=True)
                with atomic_write(historyDumpPath, mode='wb', overwrite=True) as f:
                  cloudpickle.dump(allParamsHist, f)
              except Exception:
                io.warn(f'dumping progress failed:\n\n'+traceback.format_exc())

          # close document (will be reopened next time it is needed), 
          # i.e. restart background freecad if it is time
          if time.time()-lastFreecadRestart > freecadRestartInterval:
            lastFreecadRestart = time.time()
            self.close()

          # if penalty is below threshold -> raise EndOptimize exception
          if penalty < endIfFuncBelow:
            io.verb(f'found {penalty=} < {endIfFuncBelow=}')
            raise OptimizationEnded()

          # return the penalty value
          return penalty

        # make sure SimulationEnded exception is re-raised
        except OptimizationEnded:
          raise 

        # capture any exception, log the stack trace and return ridiculously large number
        except Exception:
          io.warn(f'exception was raised in optimizer iteration:\n\n'+traceback.format_exc())
          
          # make sure freecad background process is restarted after exception
          self.close()

          # return extremely large number
          return 1e99

      # prepare arguments for minimizer: if params have both limits set, renormalize to (0,1) interval
      _b = self.bounds()
      _p = self.parameters()
      x0 = [(_p[k]-_b[k][0])/(_b[k][1]-_b[k][0]) if all(isfinite(_b[k])) else _p[k] for k in parameters]
      bounds = [[-1e-8,1+1e-8] if all(isfinite(_b[k])) else _b[k] for k in parameters]
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

      # catch and discard simulation ended exception
      except OptimizationEnded:
        io.verb(f'ending optimization')
        pass

      # before returning, make sure parameters for global optimum are set
      finally:
        if bestParametersSoFar:
          self.set(**bestParametersSoFar)
          self.save()
