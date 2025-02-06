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

from .. import io
from ..simulation import processes
from . import progress

# signal handler that kills all running freecad processes
# in case this process is killed
def handler(signum, frame):
  io.info(f'signal handler called with signal {signum}')
  for doc in _ALL_DOCUMENTS:
    doc.close()

# register signal handlers
for sig in (signal.SIGHUP, signal.SIGTERM):
  signal.signal(sig, handler)

# list that holds all ever opened documents
_ALL_DOCUMENTS = []


class FreecadProperty:
  '''
  FreecadProperty represents a property of an object in the document tree and can 
  be created from normal python shells without any connection to FreeCAD. It can 
  be read from and written to as if it was the real freecad property. All 
  read/writes will be forwarded to the running Freecad child process.
  '''
  def __init__(self, doc, obj, path):
    self.__dict__['_doc'] = doc
    self.__dict__['_obj'] = obj
    self.__dict__['_path'] = path
    self._ensureExists()

  def __repr__(self):
    return self.__str__()

  def __str__(self):
    return f'<FreecadProperty {os.path.basename(self._doc._path)}: {self._obj}.{self._path}>'

  def _freecadShellRepr(self):
    return f'App.activeDocument().getObject("{self._obj}").{self._path}'

  def _ensureExists(self):
    if ((out:=self._doc.query(
            f'try: ',
            f'  {self._freecadShellRepr()}',
            f'except Exception: ',
            f'  print("failed") ',
            f'else: ',
            f'  print("success")',
            expect=['failed', 'success']
        )) != 'success'):
      raise ValueError(f'property {self} does not exist')

  def __setattr__(self, key, value):
    if ((out:=self._doc.query(
            f'try: ',
            f'  {self._freecadShellRepr()}.{key} = {value}',
            f'except Exception: ',
            f'  print("failed") ',
            f'else: ',
            f'  print("success")', 
            expect=['failed', 'success']
        )) != 'success'):
      raise RuntimeError(f'failed setting {key} of {self} to {value}: {out}')

  def __getattr__(self, key):
    return FreecadProperty(self._doc, self._obj, f'{self._path}.{key}')

  def __call__(self, *args, **kwargs):
    argsStr = ''
    if len(args):
      argsStr += f'*{args}'
    if len(kwargs):
      if len(argsStr):
        argsStr += ', '
      argsStr += f'**{kwargs}'
    return FreecadProperty(self._doc, self._obj, f'{self._path}({argsStr})')

  def get(self):
    return self._doc.query(self._freecadShellRepr())


class FreecadObject:
  '''
  FreecadObject represents an object from the document tree and can be created from
  normal python shells without any connection to FreeCAD. It can be read from and
  written to as if it was the real freecad object. All read/writes will be forwarded
  to the running Freecad child process.
  '''
  def __init__(self, doc, obj):
    self.__dict__['_doc'] = doc
    self.__dict__['_obj'] = obj
    self._ensureExists()

  def __repr__(self):
    return self.__str__()

  def __str__(self):
    return f'<FreecadObject {os.path.basename(self._doc._path)}: {self._obj}>'

  def _freecadShellRepr(self):
    return f'App.activeDocument().getObject("{self._obj}")'

  def _ensureExists(self):
    if self._doc.query(f'print({self._freecadShellRepr()})') == 'None':
      raise ValueError(f'object {self} does not exist')
  
  def __setattr__(self, key, value):
    if (out:=self._doc.query(
            f'try: ',
            f'  {self._freecadShellRepr()}.{key} = {value}',
            f'except Exception: ',
            f'  print("failed") ',
            f'else: ',
            f'  print("success")', 
            expect=['failed', 'success']
         ) != 'success'):
      raise RuntimeError(f'failed setting {key} of {self} to {value}: {out}')

  def __getattr__(self, key):
    return FreecadProperty(self._doc, self._obj, key)

  def get(self):
    return self._doc.query(self._freecadShellRepr())


class FreecadDocument:
  '''
  FreecadDocument class represents a FCStd document and can be created from normal 
  python shells without any connection to FreeCAD. The FCStd file properties can
  be manipulated and optical simulations can be started as if we were running within
  the FreeCAD-shell.
  
  The document is intended to be used as a context manager to clean up after itself.
  '''
  def __init__(self, path=None, freecadExecutable=None):
    # register self in global list
    _ALL_DOCUMENTS.append(self)

    # autodetect path is none is given
    if path is None:
      _path = os.path.realpath(os.getcwd())
      while _path.count('/') > 1:
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

    # check if freecadExecutable is valid
    if freecadExecutable:
      if not os.path.exists(freecadExecutable):
        raise RuntimeError(f'path of custom freecad executable {freecadExecutable} '
                          f'does not seem to exist')
    else:
      freecadExecutable = 'FreeCAD'

    # save in attributes
    self._path = path
    self._freecadExecutable = freecadExecutable

    # generate results folder path
    self._resultsPath = path[:-6]+'.OpticsDesign'

    # setup flags
    self._isquit = False
    self._isterminate = False
    self._iskill = False
    self._isRunning = False

  def __repr__(self):
    return self.__str__()

  def __str__(self):
    return f'<FreecadDocument {os.path.basename(self._path)}>'

  ###########################################################################
  # FILE MANIPULATION/SIMULATION TRIGGER LOGIC

  def __getattr__(self, name):
    return self.getObject(name)

  def getObject(self, name):
    return FreecadObject(self, name)

  def objects(self):
    return eval(self.query(f'[o.Name for o in App.activeDocument().Objects]'))

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
          if action == 'fans' or 'single' in action:
            raise RuntimeError(f'no new results folder was created during {action} '
                              f'simulation, did you enable "Enable Store Single Shot '
                              f'Data" in the active Simulation Settings?')
          raise RuntimeError(f'no new results folder was created during {action} '
                            f'simulation, is another simulation running? '
                            f'{self._path=}, {self._resultsPath=}')
        elif len(newFolders) > 1:
          raise RuntimeError(f'somehow more than one result folder was created '
                            f'during {action} simulation, this should not be '
                            f'possible...')
        elif len(newFolders) > 1:
          raise RuntimeError(f'somehow more than one result folder was created '
                            f'during {action} simulation, this should not be '
                            f'possible...')
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
              endIfDuration = time.time()-t0

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
          raise RuntimeError(f'simulation process failed, see logfile {logfile} for details'+stacktraceGuess) 

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
    t0 = time.time()
    
    # register that this process is a jupyter process to setup logging
    processes.setupJupyterMaster(self._path)
    io.verb(f'opening {self} instance...')

    # signalizing progress tracker module that it is now allows to create
    # a global progress tracker
    progress.ALLOW_PROGRESS_TACKERS = True

    # launch child process - DONT load file here or it will be loaded without 
    #                        ViewProvider objects becausee GUI is not yet up
    self._p = subprocess.Popen([self._freecadExecutable, '-c'],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                stdin=subprocess.PIPE, 
                                text=True, bufsize=-1)
    self._isRunning = True

    # start thread the continuously reads stdout and adds results to queue
    self._q = queue.Queue()
    def readOutput():
      for line in iter(self._p.stdout.readline, ''):
        if line.strip():
          while line.endswith('\r') or line.endswith('\n'):
            line = line[:-1]
          #print(f'received line {line}')
          self._q.put(line)
        time.sleep(1e-3)
      self._p.stdout.close()
    self._t = threading.Thread(target=readOutput)
    self._t.daemon = True # thread dies with the program
    self._t.start()

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
    self._flushOutput(timeout=3600)

    # after gui is fully loaded, load document
    self.write(f'try: ',
               f'  App.openDocument({repr(self._path)})',
               f'except Exception:',
               f'  exit()')

    # flush outputs with infinite timeout to make sure loading file was completely done
    self._flushOutput(timeout=3600)

    # make sure numpy is imported globally, as numpy and as np, to ensure all numpy datatypes
    # can be constructed properly
    self.write(f'numpy',
               f'import numpy as np',
               f'from numpy import *')

    # flush outputs with infinite timeout to ensure this was successfully imported
    self._flushOutput(timeout=3600)

    # print success
    io.verb(f'done in {time.time()-t0:.1f}s')

  ###########################################################################
  # SUBPROCESS IO LOGIC

  def write(self, *data):
    cmdStr = '\r\n'+'\r\n'.join(data)+'\r\n'*5 # add plenty of newlines at the and to
                                               # make sure command is complete
    #print(f'sending python:')
    #print(cmdStr)
    self._p.stdin.write(cmdStr)
    self._p.stdin.flush()

  def _flushOutput(self, timeout=3):
    t0 = time.time()

    # throw away any previous content
    self.read()

    # ask to print random number
    rn = f'{random.random():.8f}'
    self.write(f'print("{rn}")')

    # wait until random number appears in output
    while True:
      out = self.read()
      #print(f'waiting for {rn}, dropping {out}')

      # if random number appears in output: success
      if rn in out:
        return

      # if time is up: raise timeout error
      if time.time()-t0 > timeout:
        raise RuntimeError(f'failed to flush output buffer of FreeCAD, '
                           f'is a process featuring heavy output printing '
                           f'running?')
      time.sleep(1e-3)

  def read(self):
    result = []
    try:
      while True:
        result.append(self._q.get_nowait())
    except queue.Empty:
      pass
    return result

  def readline(self):
    try:
      return self._q.get_nowait()
    except queue.Empty:
      pass
    return None

  def query(self, *data, timeout=6, expect=None):
    t0 = time.time()

    # make sure output buffer of freecad is empty
    self._flushOutput(timeout=timeout/2)

    # send python commands
    self.write(*data)

    # wait for single line response
    while True:
      if line:=self.readline():
        if expect is not None and line not in expect:
          continue
        #print(f'query complete: {line}')
        return line
      if time.time()-t0 > timeout:
        raise RuntimeError(f'failed to fetch response to command(s) "{data}", '
                           f'is a process featuring heavy output printing running?')
      time.sleep(1e-3)

  ###########################################################################
  # SHUTDOWN LOGIC

  def __exit__(self, *args, **kwargs):
    self.close()

  def close(self):
    t0 = time.time()
    io.verb(f'closing {self} instance...')

    # save changes
    self.write('App.activeDocument().save()')

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
    progress.progressTrackerInstance(doc=self).quit()
    progress.ALLOW_PROGRESS_TACKERS = False

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
      self.write('exit()')
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
  # create dummy-document object to detect all necessary paths 
  document = FreecadDocument(*args, **kwargs)

  # launch freecad process
  p = subprocess.Popen([document._freecadExecutable, document._path],
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
  folders = [d for d in os.listdir(basePath) if d.startswith('simulation-run-')]
  indices = [int(d[len('simulation-run-'):]) for d in folders]
  return basePath, folders, indices

def rawFolders(basePath='.'):
  basePath, folders, indices = _rawFolders(basePath=basePath)
  return RawFolderRange( sorted([os.path.relpath(f'{basePath}/{f}') for f in folders]) )

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
  def __init__(self, path):
    self._path = path
    candidates = [f for f in os.listdir(self._path) 
                      if os.path.isfile(f'{self._path}/{f}') and f.startswith('uid')]
    if len(candidates) == 0:
      raise RuntimeError('invalid raw data folder: uid file missing')
    if len(candidates) > 1:
      raise RuntimeError('invalid raw data folder: more than one uid file')
    self._uid = candidates[0][4:]

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

  def loadHits(self, pattern):
    return self._load(pattern=pattern, kind='hits')

  def loadRays(self, pattern):
    return self._load(pattern=pattern, kind='rays')

  def _load(self, pattern, kind):
    result = {}
    if pattern == '*':
      pattern = '**'
    for path in glob.iglob(f'{self._path}/{pattern}/*-{kind}.pkl', recursive=True):
      try:
        with open(path, 'rb') as _f:
          hitData = pickle.load(_f)
      except Exception as e:
        io.warn(f'failed to read {kind} file {path}: {e.__class__.__name__} "{e}"')
      else:
        # merge hitData content with result dict
        for k, v in hitData.items():
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
    return result

  @functools.wraps(RawFolder.loadRays)
  def loadRays(self, *args, **kwargs):
    result = {}
    for res in [r.loadHits(*args, **kwargs) for r in self]:
      for k, v in res.items():
        _updateResultEntry(result, k, v)
    return result
