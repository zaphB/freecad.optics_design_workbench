import logging
import logging.handlers as handlers
import os
import datetime
import random

from .simulation import results_store
from .simulation import processes

_LOG_DIR             = None
_LOGFILE_NAME        = f'optics_design_workbench.log'
_ROTATE_DIR          = 'oldlogs'
_IS_INIT             = False
_IS_VERBOSE          = True

def setVerbose(isVerbose):
  global _IS_VERBOSE
  _IS_VERBOSE = bool(isVerbose)

def _logger():
  return logging.getLogger('optics_design_workbench')

def _getLogDir():
  try:
    return results_store.getResultsFolderPath()
  # runtime error is raised if no FCStd file is opened, AttributeError is
  # raised if module is not fully initialized yet. In both cases no logging
  # is yet desired.
  except (RuntimeError, AttributeError):
    return None

def _init():
  global _IS_INIT, _LOG_DIR
  if _LOG_DIR != _getLogDir():
    if processes.isMasterProcess():
      setLogfile(_getLogDir()+'/'+_LOGFILE_NAME)
    else:
      setLogfile(_getLogDir()+'/'+_LOGFILE_NAME[:-4]+f'.pid{os.getpid()}')

  if _LOG_DIR is None:
    return

  os.makedirs(_LOG_DIR, exist_ok=True)
  for oldlog in [f for f in os.listdir(_LOG_DIR)
                    if f != _LOGFILE_NAME and f.startswith(_LOGFILE_NAME)]:
    os.makedirs(_LOG_DIR+'/'+_ROTATE_DIR, exist_ok=True)
    os.rename(_LOG_DIR+'/'+oldlog, _LOG_DIR+'/'+_ROTATE_DIR+'/'+oldlog)

  if not _IS_INIT:
    h = handlers.TimedRotatingFileHandler(_LOG_DIR+'/'+_LOGFILE_NAME, when='W6')
    h.setFormatter(
          logging.Formatter(
              r'%(asctime)s.%(msecs)03d000000 %(levelname)s: %(message)s',
              datefmt=r'%Y-%m-%dT%H:%M:%S'))
    l = _logger()
    l.addHandler(h)
    _logger().setLevel(logging.INFO)
    _IS_INIT = True


def setLogfile(name):
  '''
  change name (and path) of active logfile
  '''
  global _IS_INIT, _LOGFILE_NAME, _LOG_DIR
  # close old logfile if logger already existed
  if _IS_INIT:
    for h in _logger().handlers:
      h.close()
  name = os.path.abspath(str(name))
  baseDir = None
  if '/' in name:
    baseDir, name = os.path.split(name)
  if not name.endswith('.log'):
    name += '.log'
  _logger().handlers.clear()
  _IS_INIT = False
  _LOGFILE_NAME = name
  if baseDir is not None:
    _LOG_DIR = baseDir
  _init()

def _gatherSlaveFiles():
  '''
  collect all log files of slaves and merge with master log, only runs if this
  process is the master process
  '''
  if not _IS_INIT or not processes.isMasterProcess():
    return

  for f in os.listdir(_LOG_DIR):
    # check if file looks like a slave's log
    if f.startswith('optics_design_workbench.pid') and f.endswith('.log'):
      pid = None
      try:
        pid = int(f[27:-4])
      except ValueError:
        pass
      if pid:

        # rename file to prevent new lines being written while we parse it
        # the slave process will recreate its own logfile if new messages appear
        while True:
          tmpName = f'{_LOG_DIR}/{int(random.random()*1e12)}.log'
          if not os.path.exists(tmpName):
            break
        os.rename(_LOG_DIR+'/'+f, tmpName)

        # append file to main log
        with open(tmpName, 'r') as inFile:
          with open(_LOG_DIR+'/'+_LOGFILE_NAME, 'a') as outFile:
            for line in inFile:
              outFile.write(f'{" ".join(line.split()[:2])} (slave {pid}) {" ".join(line.split()[2:])}')
        
        # remove tempfile
        os.remove(tmpName) 

def _indentMsg(msg):
  ls = [l for l in '\n'.join([str(l) for l in msg]).split('\n') if l.strip()]
  if len(ls) == 0:
    return ''
  if len(ls) == 1:
    return ls[0]
  elif len(ls) == 2:
    return ls[0]+'\n'+' '*2+r'\ '+ls[1]
  else:
    return ('\n'+' '*2+'| ').join(ls[:-1])+'\n'+' '*2+r'\ '+ls[-1]

def _prefix(kind=''):
  prefix = datetime.datetime.now().strftime('[Optics Design %H:%M:%S.%f] ')
  if kind:
    prefix += kind.upper()+': '
  return prefix

def err(*msg, logOnly=False):
  _init()
  _gatherSlaveFiles()
  msg = _indentMsg(msg)
  if _logger():
    _logger().error(msg)
  if not logOnly:
    print(_prefix('error')+msg)
    if '\n' in msg:
      print()

def formatErr(*msg):
  return 'error: '+_indentMsg(msg)

def warn(*msg, logOnly=False):
  _init()
  _gatherSlaveFiles()
  msg = _indentMsg(msg)
  if _logger():
    _logger().warning(msg)
  if not logOnly:
    print(_prefix('warning')+msg)
    if '\n' in msg:
      print()

def info(*msg, logOnly=False, noNewLine=False):
  _init()
  _gatherSlaveFiles()
  msg = _indentMsg(msg)
  if _logger():
    _logger().info(msg)
  if not logOnly:
    print(_prefix()+msg)
    if '\n' in msg and not noNewLine:
      print()

def verb(*args, **kwargs):
  if not _IS_VERBOSE:
    return
  info(*args, **kwargs)

