import threading
import time
import functools

from . import freecad_document

CLOSE_FREECAD_TIMEOUT = 20


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

        # clear parameter cache after newly opened file
        self.parameters.cache_clear()

        # setup background thread that closes document after some inactivity
        self._closeDocumentAfterInactivityThread = threading.Thread(target=self._closeOnInactivity)
        self._closeDocumentAfterInactivityThread.start()
  
  def _parameterNodeDict(self):
    with self._freecadDocumentLock:
      self.open()
      return self._getParametersFunc(self._freecadDocument)

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
