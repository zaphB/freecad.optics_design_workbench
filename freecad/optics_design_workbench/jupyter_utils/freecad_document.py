'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *
import os
import subprocess
import time
import signal
import threading
import queue
import random
import functools
import glob
import pickle
import shutil
import traceback
from atomicwrites import atomic_write

from .. import io
from ..simulation import processes
from . import progress
from . import hits
from . import parameter_sweeper

_PRINT_FREECAD_COMMUNICATION = False
_PRINT_SETTER_AND_CALL_LINES = False

# signal handler that kills all running freecad processes
# in case this process is killed
def handler(signum, frame):
  io.info(f'signal handler called with signal {signum}')
  try:
    for doc in _ALL_DOCUMENTS:
      doc.close()
  except Exception:
    io.warn(f'exception raised in signal handler:\n\n'+traceback.format_exc())
  finally:
    exit(signum)

# register signal handlers
for sig in (signal.SIGHUP, signal.SIGTERM):
  signal.signal(sig, handler)

# list that holds all ever opened documents
_ALL_DOCUMENTS = []

# default path to freecad executable
_DEFAULT_FREECAD_EXECUTABLE = 'FreeCAD'


def setDefaultFreecadExecutable(path):
  global _DEFAULT_FREECAD_EXECUTABLE

  # check if path points to executable file if path looks like a filesystem path
  if '/' in path:
    # make sure to expand user
    path = os.path.expanduser(path)

    # check if path exists
    if not os.path.exists(path):
      raise ValueError(f'path {path} does not exist in filesystem')

    # check if regular file (if not on PATH)
    if not os.path.isfile(path):
      raise ValueError(f'path {path} is not looking like a file, did '
                      f'you specify the full path to the FreeCAD executable '
                      f'or AppImage?')

    # check if path is executable (if not on PATH)
    if not os.access(path, os.X_OK):
      raise ValueError(f'path {path} is missing executable rights, did '
                      f'you specify the full path to the FreeCAD executable '
                      f'or AppImage?')

    # replace path with absolute path
    path = os.path.abspath(path)

  else:
    try:
      p = subprocess.run(['whereis', path], capture_output=True, text=True)
    except Exception as e:
      io.warn(f'failed to check whether path exists ({e.__class__.__name__}: {str(e)})')
    else: 
      if not len(''.join(p.stdout.split(':')[1:]).strip()):
        raise ValueError(f'path {path} is not found by whereis')

  # store absolute path in global var
  _DEFAULT_FREECAD_EXECUTABLE = path


def freecadVersion():
  p = subprocess.Popen([_DEFAULT_FREECAD_EXECUTABLE, '-c'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.PIPE, 
                        text=True, bufsize=-1)
  try:
    time.sleep(.3)
    p.stdin.write('import FreeCAD; print("version follows"); print(FreeCAD.Version());\n\n')
    p.stdin.flush()
    while True:
      l = p.stdout.readline()
      if 'version follows' in l:
        l = p.stdout.readline()
        return '.'.join([e.strip()[1:-1] for e in l[1:-1].split(',')[:3]])
  except Exception:
    return None
  finally:
    p.stdin.write('\n\nexit();\n\n'*5)
    p.stdin.flush()
    time.sleep(.1)
    if p.poll() is None:
      p.kill()


# create aliases for FreeCAD types that just return simple numpy arrays
# to allow converting Vectors from FreeCAD side automatically
def Vector(*a):
  return array(a)
def Matrix(*a):
  return array(a)



class FreecadExpression:
  def __init__(self, exprString):
    self._exprString = exprString

  def _freecadShellRepr(self):
    return self._exprString

  def __repr__(self):
    return self._exprString


class FreecadPropertyDict:
  def __init__(self, d):
    self._d = d

  def __str__(self):
    return repr(self)

  def __repr__(self):
    return f'<FreecadPropertyDict {repr(self._d)} >'

  def __getattr__(self, k):
    return getattr(self._d, k)

  def __getitem__(self, k):
    return self._d[k]

  def __setitem__(self, k, v):
    self._d[k].set(v)


class FreecadConstraintDict(FreecadPropertyDict):
  def __init__(self, constraintDict, indexDict, sketch):
    self._d = constraintDict
    self._indexDict = indexDict
    self._sketch = sketch

  def __setitem__(self, k, v):
    self._sketch.setDatumWrapped(self._indexDict[k], v)


class FreecadProperty:
  '''
  FreecadProperty represents a property of an object in the document tree and can 
  be created from normal python shells without any connection to FreeCAD. It can 
  be read from and written to as if it was the real freecad property. All 
  read/writes will be forwarded to the running Freecad child process.
  '''
  def __init__(self, doc, obj, path, isCall=False, internalObjectName=False):
    self.__dict__['_doc'] = doc
    self.__dict__['_obj'] = obj
    self.__dict__['_path'] = path
    self.__dict__['_internalObjectName'] = internalObjectName
    self.__dict__['_isConstraint'] = False
    self.__dict__['_sketchObjReference'] = None
    self._ensureExists(isCall=isCall)

  def __repr__(self):
    return self.__str__()

  def __str__(self):
    return f'<FreecadProperty {self._obj}.{self._path}, value: {self.getStr()}>'

  def _freecadShellRepr(self):
    if self._internalObjectName:
      return f'App.activeDocument().getObject("{self._obj}").{self._path}'    
    return f'App.activeDocument().getObjectsByLabel("{self._obj}")[0].{self._path}'

  def _ensureExists(self, isCall=False):
    # log in case of function call
    if isCall:
      if _PRINT_SETTER_AND_CALL_LINES:
        io.verb(f'running call line: {self._freecadShellRepr()}')
      pass
    
    # if fast mode is enabled, skip any existCheck and run calls without waiting for response
    if self._doc._fastModeEnabled():
      if isCall:
        self._doc.write(self._freecadShellRepr())

    # run proper query and error checking if not in fast mode
    else:
      try:
        rn = f'{random.random():.8f}'
        self._doc.query(f'{self._freecadShellRepr()}; print("success{rn}")', expect=f'success{rn}',
                        errText=f'property {self} does not exist')
      except Exception:
        io.warn(f'running {"call" if isCall else "ensureExists"} line failed: {self._freecadShellRepr()}')
        raise

  # ----------------------------------
  # ITEM AND ATTRIBUTE ACCESS

  def set(self, value, lvalSuffix='', **kwargs):
    if self._isConstraint:
      return self.setDatumWrapped(self._constraintIndex, value)
    else:
      setterLine = f'{self._freecadShellRepr()}{lvalSuffix} = {repr(value)}'
      if _PRINT_SETTER_AND_CALL_LINES:
        io.verb(f'running setter line: {setterLine.strip()}')

      # if fast mode is enabled run setter line without waiting for response
      if self._doc._fastModeEnabled():
        self._doc.write(setterLine)

      # run proper query and error checking if not in fast mode
      else:
        rn = f'{random.random():.8f}'
        self._doc.query(f'{setterLine}; print("success{rn}")', expect=f'success{rn}',
                        errText=f'failed running python line in FreeCAD: {setterLine.strip()}')

  def setDatumWrapped(self, constraintIndex, v):
      # select good unit for value
      if abs(v) < 1e-6:
        unit = 'nm'
        _v = 1e6*v
      elif abs(v) < 1e-3:
        unit = 'um'
        _v = 1e3*v
      else:
        unit = 'mm'
        _v = v
      # return expression
      valueExpr = FreecadExpression(f'App.Units.Quantity("{_v:.6f} {unit}")')
      
      # force careful flush before and after setDatum, because strange "invalid constraint index" may occur otherwise
      for retry in range(99):
        result = self._sketchObjReference.setDatum(constraintIndex, valueExpr)
        self._doc._flushOutput(forceCareful=True, keepErrs=True)
        if err:=self._doc.readErr():
          if retry > 5:
            raise RuntimeError(f'setting datum {constraintIndex} of {self} failed: {err}')
          io.warn(f'error {err} occurred while setting a datum, retrying...')
          self._doc._flushOutput(forceCareful=True)
          time.sleep(0.1*2**retry)
        else:
          break
      return result

  def __setattr__(self, key, value):
    self.set(value, lvalSuffix=f'.{key}')

  def __getattr__(self, key):
    return FreecadProperty(self._doc, self._obj, f'{self._path}.{key}', 
                           internalObjectName=self._internalObjectName)

  def __setitem__(self, key, value):
    self.set(value, lvalSuffix=f'[{repr(key)}]')

  def __getitem__(self, key):
    return FreecadProperty(self._doc, self._obj, f'{self._path}[{repr(key)}]', 
                           internalObjectName=self._internalObjectName)

  def __len__(self):
    return int( self._doc.query( f'len( {self._freecadShellRepr()} )' ) )

  def __iter__(self):
    return iter([self[i] for i in range(len(self))])

  def __call__(self, *args, **kwargs):
    argsStr = ''
    if len(args):
      argsStr += f'*{args}'
    if len(kwargs):
      if len(argsStr):
        argsStr += ', '
      argsStr += f'**{kwargs}'
    p = FreecadProperty(self._doc, self._obj, f'{self._path}({argsStr})', isCall=True, 
                        internalObjectName=self._internalObjectName)

  def getStr(self):
    if self._isConstraint:
      return self.Value.getStr()
    return self._doc.query(self._freecadShellRepr())

  def getFloat(self):
    return float(self.getStr())
  
  def getInt(self):
    return float(self.getStr())

  def get(self):
    _str = self.getStr()
    try:
      return eval(_str)
    except Exception:
      return _str

  # ----------------------------------
  # CUSTOM ATTRIBUTES AND METHODS
  def markAsConstraint(self, sketchObj, sketchIndex):
    self.__dict__['_isConstraint'] = True
    self.__dict__['_sketchObjReference'] = sketchObj
    self.__dict__['_constraintIndex'] = sketchIndex
    return self

  def getConstraintsByName(self):
    indexAndConstraints = { c.Name.get().strip(): (i, c.markAsConstraint(self, i))
                                            for i, c in enumerate(self.Constraints)
                                                              if c.Name.get().strip() }
    return FreecadConstraintDict(constraintDict={k:v[1] for k,v in indexAndConstraints.items()},
                                 indexDict={k:v[0] for k,v in indexAndConstraints.items()},
                                 sketch=self)


class FreecadObject(FreecadProperty):
  '''
  FreecadObject represents an object from the document tree and can be created from
  normal python shells without any connection to FreeCAD. It can be read from and
  written to as if it was the real freecad object. All read/writes will be forwarded
  to the running Freecad child process.
  '''
  def __init__(self, doc, obj, internalObjectName=False):
    self.__dict__['_doc'] = doc
    self.__dict__['_obj'] = obj
    self.__dict__['_internalObjectName'] = internalObjectName
    self._ensureExists()

  def __str__(self):
    return f'<FreecadObject {os.path.basename(self._doc._path)}: {self._obj}>'

  def _freecadShellRepr(self):
    if self._internalObjectName:
      return f'App.activeDocument().getObject("{self._obj}")'
    return f'App.activeDocument().getObjectsByLabel("{self._obj}")[0]'

  def _ensureExists(self):
    # ensure at exactly one object exists
    if not self._internalObjectName:
      try:
        # force careful flushing because we need the exact response to object count also in fastMode
        self._doc._flushOutput(forceCareful=True)
        objectCount = int(self._doc.query(f'print(len( App.activeDocument().getObjectsByLabel("{self._obj}") ))'))
        # zero objects with given label exist -> fail
        if objectCount == 0:
          raise ValueError(f'object with label {self._obj} does not exist.')
        # more than one object with given label exist -> fail
        if objectCount != 1:
          raise ValueError(f'object label {self._obj} is not unique, consider to rename it '
                           f'or to use the internal name instead.')

      # handle value errors by retrying with "internal name" style instead of label
      except ValueError:
        self.__dict__['_internalObjectName'] = True
        self._ensureExists()

    # make sure self._freecadShellRepr() evaluates fine
    try:
      queryResponse = self._doc.query(f'print({self._freecadShellRepr()})')
      if queryResponse == 'None':
        raise ValueError(f'expected freecad object, found None')
    except Exception:
      raise ValueError(f'object with {"internal name" if self._internalObjectName else "label"} {self._obj} does '
                       f'not exist in freecad document (see exceptions above for detailed reason)')
  
  def __setattr__(self, key, value):
    self.__getattr__(key).set(value)

  def __getattr__(self, key):
    return FreecadProperty(self._doc, self._obj, key, 
                           internalObjectName=self._internalObjectName)


class FreecadDocument:
  '''
  FreecadDocument class represents a FCStd document and can be created from normal 
  python shells without any connection to FreeCAD. The FCStd file properties can
  be manipulated and optical simulations can be started as if we were running within
  the FreeCAD-shell.
  
  The document is intended to be used as a context manager to clean up after itself.
  '''
  def __init__(self, path=None, openFreshCopy=False):
    # register self in global list
    _ALL_DOCUMENTS.append(self)

    # autodetect path is none is given
    if path is None:
      _path = os.path.realpath(os.getcwd())
      while _path.count('/') != 1:
        if _path.endswith('.OpticsDesign'):
          candidate = _path[:-13]+'.FCStd'
          if os.path.exists(candidate):
            path = candidate
            break
        _path = os.path.dirname(_path)
      else:
        raise RuntimeError('failed to autodetect path of FCStd project file')
    if not os.path.exists(path):
      raise ValueError(f'path to freecad project file {path} does not seem to exist')
    if not path.endswith('.FCStd'):
      raise ValueError(f'path to freecad project file {path} does end with .FCStd')

    # if openFreshCopy is True, create temp folder, copy freecad file in there, 
    # and modify path attributes accordingly
    self._openFreshCopy = openFreshCopy
    self._originalPath = path
    if openFreshCopy:
      # find unique filename for FCStd file
      tempDirName = self._getTempFolder()
      while True:
        uniqueName = f'{os.path.basename(path)[:-6]}-{int(time.time()*1e3)}-pid{os.getpid()}-thread{threading.get_ident()}.FCStd'
        if not os.path.exists(f'{tempDirName}/{uniqueName}'):
          break

      # copy FCStd file to temp dir
      _target = f'{tempDirName}/{uniqueName}'
      os.makedirs(os.path.dirname(_target), exist_ok=True)
      shutil.copy(path, _target)

      # modify path variable for following initialization
      path = f'{tempDirName}/{uniqueName}'

    # save in attributes
    self._path = path

    # generate results folder path
    self._resultsPath = path[:-6]+'.OpticsDesign'

    # setup flags
    self._isquit = False
    self._isterminate = False
    self._iskill = False
    self._isRunning = False
    self._freecadInteractionTimesList = [time.time()]
    self._previousFastModeEnabled = False

  def __repr__(self):
    return self.__str__()

  def __str__(self):
    return f'<FreecadDocument {os.path.basename(self._path)}>'

  def resultsPath(self):
    return self._resultsPath

  def _getTempFolder(self, create=False):
    tempDirName = f'{self._originalPath[:-6]}.OpticsDesign/tmp'
    os.makedirs(tempDirName, exist_ok=True)
    return tempDirName

  def purgeTempFolder(self):
    # dont clean if this is a tmp-document
    if self._openFreshCopy:
      raise ValueError(f'this freecad document was opened using openFreshCopy=True, '
                       f'can only purge temp folder from instances that were opened '
                       f'without openFreshCopy option')
    shutil.rmtree(self._getTempFolder())

  def isOpenFreshCopy(self):
    if self._openFreshCopy:
      return True
    return '.OpticsDesign/tmp'.lower() in self._path.lower()

  def _sanitizeTempFolder(self, timeout=4):
    # dont clean if this is a tmp-document
    if self.isOpenFreshCopy():
      return

    t0 = time.time()
    _tmp = self._getTempFolder(create=False)
    lastWarn = time.time()
    if os.path.exists(_tmp):

      # retry cleanup on fail
      cleanedSomething = True 
      while cleanedSomething:
        maxLevel = 3 # <- recurse down to tmp/...OpticsDesign/raw/sim... level but not deeper
        try:
          cleanedSomething = False

          # walk through tmp-dir tree and delete anything that 
          # did not change for more than a day, remove empty
          # directories
          for r, dirs, files in os.walk(_tmp, topdown=True):
            # remove empty dirs
            for d in dirs:
              if not len(os.listdir(f'{r}/{d}')):
                os.rmdir(f'{r}/{d}')
                cleanedSomething = True

            # remove dirs on third sublevel by age
            dirLevel = r.count('/') - _tmp.count('/') 
            if dirLevel >= maxLevel:
              for d in dirs:
                maxAge = 24*60*60
                if time.time()-os.stat(f'{r}/{d}').st_mtime > maxAge:
                  shutil.rmtree(f'{r}/{d}')
                  cleanedSomething = True
            
            # do not recurse deeper then to third sublevel
            if dirLevel >= maxLevel:
              dirs[:] = []
            
            # remove old files
            for f in files:
              #io.verb(f'checking {dirLevel=} {r}/{f}')
              maxAge = 24*60*60
              if f.endswith('FCStd'):
                maxAge = 7*24*60*60
              try:
                if time.time()-os.stat(f'{r}/{f}').st_mtime > maxAge:
                  os.remove(f'{r}/{f}')
                  cleanedSomething = True
              except Exception as e:
                pass

            # apologize if cleaning takes long
            if time.time()-lastWarn > 5:
              lastWarn = time.time()
              io.warn(f'sorry, house keeping of the tmp-folder '
                      f'is taking a lot of time... (cleaning since {io.secondsToStr(time.time()-t0)})')

            # abort cleaning if time is up
            if time.time()-t0 > timeout:
              io.verb(f'tmp folder clean timed out after {io.secondsToStr(time.time()-t0)}')
              return
        except Exception:
          io.warn(f'exception raised during tmp-dir cleanup:\n\n'+traceback.format_exc())
      io.verb(f'full tmp folder clean successful after {io.secondsToStr(time.time()-t0)}')

  ###########################################################################
  # FILE MANIPULATION/SIMULATION TRIGGER LOGIC

  def __getattr__(self, name):
    return self.getObject(name)

  def getObject(self, name):
    return FreecadObject(self, name)

  def objects(self, internalNames=False):
    if internalNames:
      return sorted(list(set(eval(self.query(f'[o.Name for o in App.activeDocument().Objects]')))))
    return sorted(list(set(eval(self.query(f'[o.Label for o in App.activeDocument().Objects]')))))

  def runSimulation(self, action='true', endIf=None, endIfMaxLoad=.5):
    '''
    Start a simulation. 
    
    The action argument specifies the simulation kind and has to be one of
    "true", "singletrue", "pseudo", "singlepseudo" or "fans". 
    
    The endIf argument allows to pass a custom callback which will be executed
    continuously during the simulation with the current result folder path as
    its argument.

    The endIfMaxLoad argument must be between 0.01 and 1 and specifies which 
    percentage of the overall time the endIf callback is allowed to run on 
    average. The mainloop will add delays between endIf(...)-calls. In any
    case, the endIf(..) will run not more often than once per second, and at
    least once per hour.
    '''
    try:
      # behave as slave process while simulation is running (the FreeCAD simulation master
      # running in the background wants to be master, therefore we have to step back)
      processes.jupyterBecomeSlave()

      # check actions argument
      allowedActions = 'true pseudo singletrue singlepseudo fans'.split()
      if action not in allowedActions:
        raise ValueError(f'illegal action {action}, expected one of {", ".join(allowedActions)}')

      # save list of existing raw data folders
      rawFoldersBefore = []
      if os.path.exists(self._resultsPath+'/raw'):
        rawFoldersBefore = os.listdir(self._resultsPath+'/raw')

      # subfunction to detect new results folder
      def newFolder(allowEmpty=True):
        # find and return newly appeared folder in results dir
        newFolders = []
        if os.path.exists(self._resultsPath+'/raw'):
          newFolders = [d for d in os.listdir(self._resultsPath+'/raw')
                                                if d not in rawFoldersBefore]

        # check plausibility of result
        if len(newFolders) == 0 and not allowEmpty:

          # no new folder appeared, show different exception texts depending on 
          # fans/single or if error output occurred
          if action == 'fans' or 'single' in action:
            raise RuntimeError(f'no new results folder was created during {action} '
                              f'simulation, did you enable "Enable Store Single Shot '
                              f'Data" in the active Simulation Settings?'
                              +self._errorOutText())
          raise RuntimeError(f'no new results folder was created during {action} '
                             f'simulation, is another simulation running? '
                             f'{self._path=}, {self._resultsPath=}'
                             +self._errorOutText())
        
        # more than one new folder appeared
        elif len(newFolders) > 1:
          raise RuntimeError(f'somehow more than one result folder was created '
                            f'during {action} simulation, this should not be '
                            f'possible...'
                            +_errorOutText())
        # return result
        return RawFolder(f'{self._resultsPath}/raw/{newFolders[0]}') if len(newFolders) else None 

      # write command
      self.write(f'from freecad.optics_design_workbench import simulation',
                 f'simulation.runSimulation(action="{action}")')

      # start progress tracker background thread
      progressTracker = progress.progressTrackerInstance(doc=self)

      # start mainloop that detects end of simulation and endIf-calls
      possibleStacktrace = []
      try:
        lastSentRandom = 0
        lastEndIfCheck = time.time()
        endIfDuration = 0
        rn, l = None, None
        while rn is None or rn != l:
          # ask to print random number every 60 seconds 
          if time.time()-lastSentRandom > 60:
            rn = f'{random.random():.8f}'
            self.write(f'print("{rn}")')
            lastSentRandom = time.time()

          # check for new folders and update simulation tracker folder if so
          _newFolder = newFolder()
          progressTracker.resultsFolder = _newFolder

          # check custom simulation-end criterion with ~50% dutycycle
          if ( endIf is not None 
                and time.time()-lastEndIfCheck
                      > min([60*60, max([1, 1/max([0.01, endIfMaxLoad]) * endIfDuration ]) ]) ):
            lastEndIfCheck = time.time()
            if _newFolder is not None:
              # if endIf callback returns True, place simulation-done file
              _t0 = time.time()
              if endIf(_newFolder):
                with open(f'{self._resultsPath}/simulation-is-done', 'w') as _:
                  pass
              endIfDuration = time.time()-_t0

          # if random number appears in output the simulation must be done
          for l in self.read():
            if rn and rn == l:
              break

            # if line looks like the beginning of a stacktrace, reset stacktrace buffer
            if 'traceback (most recent call last)' in l.lower():
              possibleStacktrace = []
            possibleStacktrace.append(l)

          # limit loop speed
          time.sleep(1e-2)

        # presence of simulation-canceled file or absence of simulation-is-done file indicates
        # that simulation was ended by an exception: raise this exception
        if (os.path.exists(f'{self._resultsPath}/simulation-is-canceled') 
                or not os.path.exists(f'{self._resultsPath}/simulation-is-done')):
          stacktraceGuess = ''
          if len((''.join(possibleStacktrace)).strip()):
            stacktraceGuess = f'; I guess it has something to do with this output:\n\n'+'\n'.join(possibleStacktrace)
          logfile = os.path.relpath(self._resultsPath+'/optics_design_workbench.log')
          raise RuntimeError(f'simulation process failed, see logfile {logfile} for details'
                              +stacktraceGuess
                              +self._errorOutText())

        # return new results folder generated during the simulation
        return newFolder(allowEmpty=False)

      # clean up progress tracker
      finally:
        # increment progress tracker iteration count
        progressTracker.nextIteration()

    # let jupyter become master again after simulation is done
    finally:
      processes.jupyterBecomeMaster()

  ###########################################################################
  # LAUNCH LOGIC

  def __enter__(self):
    self.open()
    return self

  def open(self):
    self._updateInteractionTime()
    t0 = time.time()
    
    # register that this process is a jupyter process to setup logging
    processes.setupJupyterMaster(self._path)
    io.verb(f'opening {self} instance...')

    # signalizing progress tracker module that it is now allows to create
    # a global progress tracker
    progress.ALLOW_PROGRESS_TACKERS = True

    # launch child process - DONT load file here or it will be loaded without 
    #                        ViewProvider objects because GUI is not yet up
    self._p = subprocess.Popen([_DEFAULT_FREECAD_EXECUTABLE, '-c'],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE, 
                                text=True, bufsize=-1)
    self._isRunning = True

    # start thread the continuously reads stdout and adds results to queue
    self._q = queue.Queue()
    self._qe = queue.Queue()
    def readOutput():
      for line in iter(self._p.stdout.readline, ''):
        if line.strip():
          # remove line ending characters
          while line.endswith('\r') or line.endswith('\n'):
            line = line[:-1]
          #print(f'received line {line}')
          self._q.put(line)
        #time.sleep(1e-6)
      self._p.stdout.close()
    self._t = threading.Thread(target=readOutput)
    self._t.daemon = True # thread dies with the program
    self._t.start()

    def readError():
      for line in iter(self._p.stderr.readline, ''):
        # remove prompt characters from beginning of line
        while line.lstrip().startswith('>>>') or line.lstrip().startswith('...'):
          line = line.lstrip()[4:]

        # not-important-list: ignore some well known errors which are rather warnings than errors:
        if any([p.lower() in line.lower() for p in (
              'Updating geometry: Error build geometry',
              'Invalid solution from', )]):
          io.warn(f'ignoring FreeCAD error output {repr(line.strip())}')
          line = ''

        # very-important-list: raise certain errors immediately, as they indicate a broken document state:
        if any([p.lower() in line.lower() for p in (
             'BRep_API: command not done', 'Revolution: Revolve axis intersects the sketch',)]):
          raise RuntimeError(f'FreeCAD reported error: {line}')

        if line.strip():
          # remove line ending characters and add to queue
          while line.endswith('\r') or line.endswith('\n'):
            line = line[:-1]
          io.warn(f'received error line {repr(line)}', logOnly=True)
          self._qe.put(line)
        time.sleep(1e-3)
      self._p.stdout.close()
    self._te = threading.Thread(target=readError)
    self._te.daemon = True # thread dies with the program
    self._te.start()

    # Send python snippet to load GUI and immediately hide window, this allows to run
    # in a "headless-like" mode but still loads all ViewProvider objects. In true headless
    # mode without the ViewProvider objects, saving the file will break many things, because
    # all View Properties are lost then. Exit on error to make failure visible to this
    # process (we dont read stdout/stderr and only realize something is wrong if the child dies)
    # The second half of the snippets makes sure all other gui windows the workbench might want
    # to open remain hidden (or do not open at all)
    self.write(f'try: ',
               f'  import FreeCADGui as Gui',
               f'  Gui.showMainWindow()',
               f'  Gui.getMainWindow().hide()',
               f'  ',
               f'  from freecad.optics_design_workbench.gui_windows import common',
               f'  common.HIDE_GUI = True',
               f'except Exception:',
               f'  exit()')

    # flush outputs with infinite timeout to make sure startup was completely done
    self._flushOutput(forceCareful=True)

    # after gui is fully loaded, load document
    self.write(f'try: ',
               f'  App.openDocument({repr(self._path)})',
               f'except Exception:',
               f'  exit()')

    # flush outputs with infinite timeout to make sure loading file was completely done
    self._flushOutput(forceCareful=True)

    # make sure numpy is imported globally, as numpy and as np, to ensure all numpy datatypes
    # can be constructed properly
    self.write(f'import numpy',
               f'import numpy as np',
               f'from numpy import *')

    # flush outputs with infinite timeout to ensure this was successfully imported
    self._flushOutput(forceCareful=True)

    # clear interaction time list to avoid immediately triggering fast mode
    self._forceDisableFastMode()

    # print success
    io.verb(f'done in {time.time()-t0:.1f}s')


  ###########################################################################
  # SUBPROCESS IO LOGIC

  def _errorOutText(self):
    'return a string to append to exceptions which hints to freecad error output'
    errorOut = self.readErr()
    if not errorOut.strip():
      return ''
    return (f'\n\nFreecad process had possibly related '
            f'error output recently:\n\n{errorOut}')

  def lastInteractionTime(self):
    return self._freecadInteractionTimesList[-1]

  def _updateInteractionTime(self):
    self._freecadInteractionTimesList.append(time.time())
    T = array(self._freecadInteractionTimesList)
    self._freecadInteractionTimesList[:] = T[time.time()-T < 30]

  def _forceDisableFastMode(self):
    self._freecadInteractionTimesList[:] = [time.time()]

  def _fastModeEnabled(self):
    T = array(self._freecadInteractionTimesList)

    # enable fast mode if more than 100 freecad interactions
    # within last 3 seconds, only disable if less then 100
    # interactions within 10 seconds 
    #io.verb(f'{sum( time.time()-T < 5 )=}')
    if self._previousFastModeEnabled:
      enable = sum( time.time()-T < 10 ) > 100
    else:
      enable = sum( time.time()-T < 3 ) > 100

    # if fast mode was just ended, make sure to flush buffers
    if not enable and self._previousFastModeEnabled:
      self._flushOutput(forceCareful=True)

    # update previousFastMode attribute and log if fastModeEnable changed
    if enable != self._previousFastModeEnabled:
      io.verb(f'{"enabled" if enable else "disabled"} freecad communication fast mode')
      self._previousFastModeEnabled = enable

    return enable

  def write(self, *data):
    self._updateInteractionTime()
    cmdStr = '\r\n'+'\r\n'.join(data)+'\r\n'*2 # add plenty of newlines at the and to
                                               # make sure command is complete also 
                                               # if indented a few levels
    if _PRINT_FREECAD_COMMUNICATION:
      io.verb('> '+cmdStr.replace('\r', '').strip('\n'))
    self._p.stdin.write(cmdStr)
    self._p.stdin.flush()

  def _flushOutput(self, timeout=60, forceCareful=False, keepErrs=False):
    self._updateInteractionTime()
    t0 = time.time()

    # throw away any previous content
    if not keepErrs:
      self.readErr()
    self.read()

    # skip careful flush if fastMode is active (and not forced)
    if forceCareful or not self._fastModeEnabled():
      lastWarned = time.time()
      lastPrintedRn = 0
      rn = None
      while True:
        # ask to print random number every few seconds 
        # (scale wait time with time that has passed)
        if time.time()-lastPrintedRn > 1/5*(time.time()-t0):
          lastPrintedRn = time.time()
          rn = f'{random.random():.8f}'
          self.write(f'print("{rn}")')
        
        # if random number appears in output: success
        out = self.read()
        #print(f'waiting for {rn}, found {out}')
        if rn in out:
          return

        # warn of takes long
        if time.time()-lastWarned > 5:
          lastWarned = time.time()
          io.warn(f'long waiting time for freecad process to become responsive, '
                  f'waiting since {io.secondsToStr(time.time()-t0)} '
                  f'(this may happen if the system is under heavy load)')

        # if time is up: raise timeout error
        if time.time()-t0 > timeout:
          raise RuntimeError(f'failed to flush output buffer of FreeCAD, '
                            f'is a process featuring heavy output printing '
                            f'running?')
        time.sleep(1e-3)

  def read(self):
    self._updateInteractionTime()
    result = []
    try:
      while True:
        result.append(self._q.get_nowait())
    except queue.Empty:
      pass
    return result

  def readErr(self):
    self._updateInteractionTime()
    result = []
    lastLineReceived = 0
    while True:
      # fetch lines until queue.Empty is raised
      try:
        while True:
          result.append(self._qe.get_nowait())
          lastLineReceived = time.time()
      except queue.Empty:
        pass

      # if a line was received once only exit after
      # no line was seen for 500ms
      if time.time()-lastLineReceived > .5:
        break

      # limit loop seed
      time.sleep(1e-3)

    return '\n'.join(result)

  def readline(self):
    self._updateInteractionTime()
    try:
      return self._q.get_nowait()
    except queue.Empty:
      pass
    return None

  def query(self, *data, timeout=60, expect=None, errText=None):
    self._updateInteractionTime()
    t0 = time.time()

    # make sure output buffer of freecad is empty (do not wait
    # full timeout to leave a bit time for the query itself)
    self._flushOutput(timeout=0.9*timeout)

    # send python commands
    self.write(*data)

    # wait for single line response
    lastWarned = time.time()
    sentCommandT0 = time.time()
    while True:
      if error:=self.readErr():
        raise RuntimeError((f'{errText.strip()}\n' if errText else '')
                           +f'exception was raised while handling '
                           +f'command(s) {data}:\n\n'+error)

      # check for result line
      if line:=self.readline():
        if _PRINT_FREECAD_COMMUNICATION:
          io.verb(f'< {line}')
        if expect is not None and expect not in line:
          continue
        return line

      # warn of takes long
      if time.time()-lastWarned > 5:
        lastWarned = time.time()
        io.warn(f'long waiting time for response from freecad process, waiting '
                f'since {io.secondsToStr(time.time()-sentCommandT0)} '
                f'(this may happen if the system is under heavy load)')

      # raise if timeout has passed
      if time.time()-t0 > timeout:
        raise RuntimeError((f'{errText.strip()}\n' if errText else '')
                           +f'failed to fetch any response to command(s) {data}, '
                           +f'is the system overloaded or is freecad running '
                           +f'something with heavy output printing running?')
      time.sleep(1e-3)

  ###########################################################################
  # SHUTDOWN LOGIC

  def __exit__(self, *args, **kwargs):
    self.close()

  def save(self):
    # send clear rays command
    self.write('Gui.runCommand("Clear all rays",0)')

    # send save document command
    self.write('App.activeDocument().save()')

  def close(self):
    t0 = time.time()
    io.verb(f'closing {self} instance...')

    # save changes to disk (if self is open)
    if self.isRunning():
      self.save()

    while self.isRunning():
      # gently ask to quit
      self._quit()

      # if not exited after three seconds, send sigterm
      if time.time()-t0 > 3:
        self._terminate()

      # if not exited after five seconds, send sigkill
      if time.time()-t0 > 5:
        self._kill()

      # limit loop speed
      time.sleep(.1)

    # make sure global progress tracker instance is shut down
    # and prevent creating new ones because we are not in the 
    # the document context manager anymore
    if progress.progressTrackerExists():
      progress.progressTrackerInstance(doc=self).quit()
      progress.ALLOW_PROGRESS_TACKERS = False

    # run temp dir cleanup
    self._sanitizeTempFolder()

    io.verb(f'done in {time.time()-t0:.1f}s')
    processes.unsetJupyterMaster()

  def isRunning(self):
    if self._isRunning:
      if (res:=self._p.poll()) is not None:
        self._isRunning = False
        io.verb(f'FreeCAD finished (exit code {res})')
    return self._isRunning

  def _quit(self):
    if self.isRunning() and not self._isquit:
      io.verb('asking FreeCAD to quit...')
      self.write('FreeCADGui.getMainWindow().deleteLater()') # <- trick to gently shut down freecad without any prompts
      #self.write('exit()') # <- dont do, exiting the python shell causes segfaults sometimes
      self._isquit = True

  def _terminate(self):
    if self.isRunning():
      if not self._isterminate:
        io.verb('terminating FreeCAD...')
        self._isterminate = True

      # place cancel file
      with open(f'{self._resultsPath}/simulation-is-canceled', 'w') as f:
        pass
      try:
        os.remove(f'{self._resultsPath}/simulation-is-running')
      except Exception:
        pass

      # close stdin and send sigterm
      try:
        self._p.stdin.close()
      except:
        pass
      self._p.send_signal(signal.SIGTERM)

  def _kill(self):
    if self.isRunning():
      if not self._iskill:
        io.verb('killing FreeCAD...')
        self._iskill = True
      self._p.send_signal(signal.SIGKILL)


@functools.wraps(FreecadDocument.__init__)
def openFreecadGui(*args, **kwargs):
  # close all sweepers that may have opened the file
  parameter_sweeper.closeAllSweepers()

  # create dummy-document object to detect all necessary paths 
  document = FreecadDocument(*args, **kwargs)

  # launch freecad process
  p = subprocess.Popen([_DEFAULT_FREECAD_EXECUTABLE, document._path],
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
  _didFinishPrint = False
  def isRunning():
    nonlocal _didFinishPrint
    if (res:=p.poll()) is not None:
      if not _didFinishPrint:
        io.verb(f'FreeCAD finished (exit code {res})')
        _didFinishPrint = True
      return False
    return True

  # block until freecad is closed, kill freecad process if ctrl+c is caught
  while isRunning():
    try: 
      # limit loop speed
      time.sleep(1/3)

    # if ctrl+c is received make sure to kill freecad
    except KeyboardInterrupt:
      # first gently...
      for _ in range(5):
        p.send_signal(signal.SIGTERM)
        time.sleep(1/2)
        if not isRunning():
          break

      # ..then not so gently
      while isRunning():
        p.send_signal(signal.SIGKILL)
        time.sleep(1/2)

      # re-raise Keyboard interrupt because absorbing a keyboard interrupt
      # is not a good idea
      raise

def _rawFolders(basePath='.'):
  # descent path until 'raw' folder is found
  while not os.path.exists(f'{basePath}/raw') and basePath != '/':
    basePath = os.path.realpath(f'{basePath}/..')
  basePath = f'{basePath}/raw'
  if not os.path.exists(basePath):
    raise ValueError(f'failed to find "raw" folder in any parent directory of {basePath=}')

  # get all simulation run folders
  folders = sorted([d for d in os.listdir(basePath) if d.startswith('simulation-run-')])
  indices = [int(d[len('simulation-run-'):]) for d in folders]
  return basePath, folders, indices

def rawFolders(basePath='.'):
  basePath, folders, indices = _rawFolders(basePath=basePath)
  return RawFolderRange( [os.path.relpath(f'{basePath}/{f}') for f in folders] )

def rawFolderByIndex(index=-1, basePath='.'):
  basePath, folders, indices = _rawFolders(basePath=basePath)

  # interpret positive indices just like number in the directory name
  if index >= 0:
    if index not in indices:
      raise ValueError(f'simulation-run folder with index {index} does not exist')
    return RawFolder(f'{basePath}/{folders[indices.index(index)]}')

  # interpret negative indices as counting from the end (ignoring directory name)
  return RawFolder(f'{basePath}/{folders[index]}')

@functools.wraps(rawFolderByIndex)
def latestRawFolder(**kwargs):
  return rawFolderByIndex(index=-1, **kwargs)

def _updateResultEntry(result, key, value):
  v = value
  k = key

  # key not yet existing: just save
  if k not in result.keys():
    result[k] = v

  # string + string = string if identical, else list of two strings
  elif type(v) in (str, str_) and type(result) in (str, str_):
    if v == result[k]:
      pass
    else:
      result[k] = [result[k], v]

  # string + list = add string to list if not existing yet
  elif type(v) in (str, str_) and type(result) not in (str, str_) and hasattr(result[k], '__iter__'):
    if v not in result[k]:
      result[k] = list(result[k]) + [v]

  # list/array + list/array = concatenate
  elif len(result[k]) == 0:
    result[k] = v
  elif len(v) == 0:
    pass
  else:
    result[k] = concatenate([result[k], v], axis=0)


class RawFolder:
  '''
  RawFolder class represents one simluation-run folder in the raw subfolder of
  the simulation results directory.
  '''
  def __init__(self, path, timeout=60):
    self._path = path

    # detect uid, wait up to timeout for uid file to show up
    t0 = time.time()
    lastWarned = time.time()
    while True:
      candidates = [f for f in os.listdir(self._path) 
                        if os.path.isfile(f'{self._path}/{f}') and f.startswith('uid')]
      # if exactly one candidate: save uid and exit loop
      if len(candidates) == 1:
        self._uid = candidates[0][4:] 
        break

      # warn if it takes long
      if time.time()-lastWarned > 3:
        lastWarned = time.time()
        io.warn(f'waiting for uid file to show up took long ({io.secondsToStr(time.time()-t0)})')

      # raise after timeout
      if time.time()-t0 > timeout:
        if len(candidates) == 0:
          raise RuntimeError('invalid raw data folder: uid file missing')
        if len(candidates) > 1:
          raise RuntimeError('invalid raw data folder: more than one uid file')

  def __repr__(self):
    return self.__str__()

  def __str__(self):
    return f'<RawFolder {os.path.basename(self._path)}/ UID={self._uid}>'

  def path(self):
    return os.path.relpath(self._path)

  def reload():
    self.tree.cache_clear()

  @functools.cache
  def tree(self, _path=None):
    '''
    Return nested directories representing the directory structure of this RawFolder
    '''
    if _path is None:
      _path = self._path
    result = {}
    folderContents = []
    for d in os.scandir(_path):
      # add subdirectory as subdictionary
      if d.is_dir():
        result[d.name] = self.tree(_path=d.path)

      # register presence of known and unknown files
      elif d.name.endswith('-hits.pkl'):
        folderContents.append('hit')
      elif d.name.endswith('-rays.pkl'):
        folderContents.append('ray')
      elif d.name.startswith('uid-') or d.name.startswith('.'):
        pass
      else:
        folderContents.append('unknown')

    # add simple string entries in dictionary for detected files
    for found in set(folderContents):
      result[f'<{folderContents.count(found)} {found} files>'] = None
    return result

  def printTree(self, _node=None, _prefix='  '):
    '''
    Pretty print the directory structure of this RawFolder
    '''
    if _node is None:
      print(f'{os.path.basename(self._path)}/')
      _node = self.tree()
    for k, v in sorted(_node.items(), key=lambda e: e[0]):
      if v is None:
        print(_prefix+k)
      elif type(v) is dict:
        print(_prefix+k+'/')
        self.printTree(_node=v, _prefix=_prefix+'  ')
      else:
        raise ValueError(f'invalid tree node {_node}')

  def loadHits(self, pattern='*'):
    return hits.Hits(self._load(pattern=pattern, kind='hits'))

  def loadRays(self, pattern='*'):
    return self._load(pattern=pattern, kind='rays')

  def _findPathsAndSanitize(self, pattern, kind, optimalFilesize=500e6):
    if pattern == '*':
      pattern = '**'
    def _makeGlob():
      return glob.iglob(f'{self._path}/{pattern}/*-{kind}.pkl', recursive=True)

    # group all files to consider by folder
    byFolder = {}
    for path in _makeGlob():
      base, name = os.path.split(path)
      if base not in byFolder.keys():
        byFolder[base] = []
      try:
        _stat = os.stat(path)
        mtime = _stat.st_mtime
        size = _stat.st_size
      except Exception:
        mtime = time.time()
        size = 1
      byFolder[base].append([name, mtime, size])

    # find files that look well suited for merging
    for base, namesTimesSizes in byFolder.items():
      mergeList = []
      sizeInList = 0
      def mergeAllInList():
        # only do something if more than one file in list
        if len(mergeList) > 1:
          # load and merge all files in list
          merged = {}
          for name in mergeList:
            try:
              with open(f'{base}/{name}', 'rb') as _f:
                data = pickle.load(_f)
            except Exception as e:
              io.warn(f'failed to read {kind} file {base}/{name}: {e.__class__.__name__} "{e}"')
            else:
              # merge file content with merged dict
              for k, v in data.items():
                _updateResultEntry(merged, k, v)
          
          # overwrite first file in list with total results
          with atomic_write(f'{base}/{mergeList[0]}',
                            mode='wb', overwrite=True) as f:
            pickle.dump(merged, f)

          # delete all remaining files in list
          for name in mergeList[1:]:
            os.remove(f'{base}/{name}')

        # reset list
        mergeList.clear()

      # only consider files that did not change in the last hour
      for name, size in sorted([(n, s) for n, t, s in namesTimesSizes if time.time()-t > 60*60],
                               key=lambda e: e[0]):
        # if this file would make the current merge collection much larger than optimal
        # size -> merge without current file
        if sizeInList+size > 1.5*optimalFilesize:
          mergeAllInList()

        # add current file to list and merge if collection is larger than optimal size
        mergeList.append(name)
        sizeInList += size
        if sizeInList > optimalFilesize:
          mergeAllInList()

      # merge leftover files no matter the total size
      mergeAllInList()

    # return all cleaned up paths
    return _makeGlob()

  def _load(self, pattern, kind):
    result = {}
    for path in self._findPathsAndSanitize(pattern, kind):
      try:
        with open(path, 'rb') as _f:
          data = pickle.load(_f)
      except Exception as e:
        io.warn(f'failed to read {kind} file {path}: {e.__class__.__name__} "{e}"')
      else:
        # merge hitData content with result dict
        for k, v in data.items():
          _updateResultEntry(result, k, v)

    return result

class RawFolderRange:
  def __init__(self, paths):
    self._paths = [p.path() if isinstance(p, RawFolder) else p for p in paths]
  
  def __iter__(self):
    return [RawFolder(p) for p in self._paths].__iter__()

  def __len__(self):
    return len(self._paths)

  def __getitem__(self, i):
    selectedPaths = self._paths[i]
    if type(selectedPaths) in (str, str_):
      return RawFolder(selectedPaths)
    return RawFolderRange(selectedPaths)

  def paths(self):
    return [os.path.relpath(p) for p in self._paths]

  @functools.wraps(RawFolder.loadHits)
  def loadHits(self, *args, **kwargs):
    result = {}
    for res in [r.loadHits(*args, **kwargs) for r in self]:
      for k, v in res.items():
        _updateResultEntry(result, k, v)
    return hits.Hits(result)

  @functools.wraps(RawFolder.loadRays)
  def loadRays(self, *args, **kwargs):
    result = {}
    for res in [r.loadRays(*args, **kwargs) for r in self]:
      for k, v in res.items():
        _updateResultEntry(result, k, v)
    return result
