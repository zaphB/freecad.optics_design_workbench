from numpy import *
from matplotlib.pyplot import *
import matplotlib.ticker
import seaborn as sns
import scipy.optimize

import threading
import time
import traceback
import functools

from .. import io
from . import freecad_document
from . import progress

CLOSE_FREECAD_TIMEOUT = 30


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
      self._freecadDocument.close()
      self._freecadDocument = None

      # clear parameter cache if file was closed
      self.parameters.cache_clear()

  def open(self):
    with self._freecadDocumentLock:
      if self._freecadDocument is None:
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
    paramNames = self._parameters().keys()
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

  def optimize(self, minimizeFunc, parameters, simulationMode, 
               prepareSimulation=None, simulationKwargs={},
               minimizeKwargs={}, progressPlotInterval=30, 
               **kwargs):

    # setup progress and timing vars
    t0 = time.time()
    lastProgressPlot = 0
    minimizeFuncHist = []
    allParamsHist = []
    bestPenaltySoFar, bestResultSoFar = inf, None

    parameters = list(parameters)
    with self._freecadDocumentLock:
      self.open()

      # wrap minimize func, run simulation before and pass additional args
      def _simulateAndMinimizeFunc(args):
        nonlocal bestPenaltySoFar, bestResultSoFar, lastProgressPlot

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
              fig, (ax1, ax2) = subplots(1, 2, figsize=(4,7))
              sca(ax1)
              sns.scatterplot(pd.DataFrame([p[:3] for p in allParamsHist]), x=0, y=1, 
                              style=2, markers=['.', '*'],
                                  ).set(xlabel='time', ylabel='penalty', yscale='log')
              gca().xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
                                                lambda x, p: io.secondsToStr(x-t0, length=1) ))

              # plot hits
              sca(ax2)
              plotHits(bestResultSoFar.loadHits('*'), *(['fanIndex', 'fan #'] if simulationMode=='fans' else []))
              tight_layout()
              show()

              # print status
              io.info(f'optimizer running since {io.secondsToStr(time.time()-t0)}')

            # calculate penalty
            penalty = minimizeFunc(resultFolder)

            # update history lists and shorten if necessary
            if penalty < bestPenaltySoFar:
              io.verb(f'found new optimum: {penalty=}, {paramDict=}')
              allParamsHist.append([time.time(), penalty, True, paramDict])
              bestPenaltySoFar = penalty
            else:
              allParamsHist.append([time.time(), penalty, False, paramDict])
            if len(allParamsHist) > 1e4:
              allParamsHist[:] = allParamsHist[::2]
            
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
      return scipy.optimize.minimize(_simulateAndMinimizeFunc, x0=x0, bounds=bounds, **minimizeKwargs) 
