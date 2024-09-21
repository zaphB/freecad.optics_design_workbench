import logging
import logging.handlers as handlers
import os
import datetime

from .simulation import results_store

_LOG_DIR             = None
_LOGFILE_NAME        = 'optics_design_workbench.log'
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
  except RuntimeError:
    return None

def _init():
  global _IS_INIT, _LOG_DIR
  if _LOG_DIR != _getLogDir():
    setLogfile(_getLogDir()+'/'+_LOGFILE_NAME)

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
  msg = _indentMsg(msg)
  if _logger():
    _logger().warning(msg)
  if not logOnly:
    print(_prefix('warning')+msg)
    if '\n' in msg:
      print()

def info(*msg, logOnly=False, noNewLine=False):
  _init()
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
