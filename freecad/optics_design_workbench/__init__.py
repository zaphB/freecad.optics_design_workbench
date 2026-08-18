
__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__version__ = None


def _determinePackageVersion():
  '''
  find out installed version of the workbench and set global variable
  '''
  global __version__
  from importlib.metadata import version
  try:
    __version__ = version('optics_design_workbench')
  except Exception:
    try:
      __version__ = version('freecad.optics_design_workbench')
    except Exception:
      try:
        import re
        import os
        with open(os.path.dirname(__file__)+'/../../package.xml') as _f:
          __version__ = re.search(r'<version>(.*)</version>', _f.read()).group(1).strip()
      except Exception:
        raise
        __version__ = '?'

# make sure __version__ is set
_determinePackageVersion()


def versionInfo(_returnText=False):
  '''
  print summary of version numbers that may be relevant for the workbench
  '''
  import sys
  import os
  FreeCAD = None
  freecadVersion = None
  try:
    import FreeCAD
  except ImportError:
    pass
  else:
    freecadVersion = ".".join(FreeCAD.Version()[:3])
  if freecadVersion is None:
    from . import jupyter_utils
    freecadVersion = jupyter_utils.freecadVersion()
  from . import detect_pyside
  res = []
  _print = print
  if _returnText:
    _print = lambda l: res.append(l)
  _print(f'python version:          {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')
  _print(f'workbench version:       {__version__}')
  _print(f'FreeCAD version:         {freecadVersion or "?"}')
  _print(f'running within FreeCAD?  {"yes" if FreeCAD else "no"}')
  if detect_pyside.detectQtMajorVersion():
    _print(f'Qt major version:        {detect_pyside.detectQtMajorVersion()}')
  _print(f'sys.prefix:              {sys.prefix}')
  _print(f'sys.base_prefix:         {sys.base_prefix}')
  try:
    import zmq
    _print(f'libzmq version:          {zmq.zmq_version()}')
    _print(f'pyzmq version:           {zmq.__version__}')
  except Exception:
    _print(f'libzmq/pyzmq:            not available')
  if _returnText:
    return '\n'.join(res)


def _hackilyUpdateSysPathIfPythonDependenciesMissing():
  '''
  Check whether dependencies are importable and inject /usr/lib paths into 
  sys.path if not the case. This used to be important because the AddOn manager
  was not able to correctly install python dependencies e.g. when using AppImage
  installations. Right now (07.2026) the AddOn manager seems to handle all
  cases well, therefore this function now emits a warning when it injects
  to sys.path and can hopefully be deprecated and removed in the future.
  '''
  # check whether all python dependencies are importable
  def importAllExceptZmq():
    import numpy, scipy, sympy, matplotlib, atomicwrites
  def importZmq():
    import zmq
  for tryImports, dependencies, severeness in (
        [importAllExceptZmq, 'atomicwrites, numpy, scipy, sympy, matplotlib', 
         "The workbench will most likely not be available in the menu, and even "
         "if it is, it will not work. Please find a way to install the python "
         "dependencies "],
        [importZmq, 'zmq (PyPi package name is pyzmq)',
         "Fortunately zmq is an optional dependency and the workbench will likely "
         "be fully functional except for some experimental features. However zmq "
         "may become a mandatory dependency in the future, so it's worthwhile "
         "finding a way to make the zmq package available in freecad's python "
         "shell sooner or later "]):
    try:
      tryImports()
    except Exception:
      # in case import fails: update sys.path
      import sys
      import os
      ma, mi = sys.version_info.major, sys.version_info.minor
      found = False

      # look for site-packages folder matching current python version, or one of the three previous
      # minor python versions or the next minor python version
      injections = []
      for d in (0, -1, -2, -3, 1, 2, 3):

        for base in ['/usr/lib', '/usr/local/lib']:
          # some systems call it /usr/lib64, some call it /usr/lib, therefore check both
          for w in ('64', ''):
            for sep in ('.', ''):
              for suff in ('.zip', '', '/lib-dynload', '/site-packages'):

                # check candidate paths and add if needed
                candidate = os.path.realpath(f'{base}{w}/python{ma}{sep}{mi+d}{suff}')
                
                if os.path.exists(candidate):
                  if candidate not in sys.path:
                    injections.append(candidate)
                    sys.path.append(candidate)

      # try import again and decide what to report
      import warnings
      import traceback
      warningTextBegin = ("\n\n***** PLEASE READ (and report) "+"*"*49+"\n\n"+"The following warning contains important "
        "information for the development of the optics_design_workbench. Please consider taking the time to "
        "create an issue here:\nhttps://github.com/zaphB/freecad.optics_design_workbench/issues\ncopying the warning "
        "below and describing the circumstances in which you encountered the warning (operating system, running "
        "GUI or headless, etc.) "
        "Thanks a lot for your help!\n\n"
        "The optics_design_workbench requires the following python package(s) to be "
        "importable in the freecad python shell: "+dependencies+". ")
      warningTextMid = ("(which will make this annoying warning disappear, too). Proper way (1) "
        "is to use the AddOn manger to install the workbench. It should take care of installing the "
        "python dependencies, but this may fail in some edge cases. Proper way (2) is to invoke pip "
        "from within the freecad python shell like this: 'import pip; pip.main(['install', 'atomicwrites'])', "
        "but again this may fail in some edge cases. ")
      try:
        tryImports()
        warnText = (warningTextBegin+"These package(s) were only importable after injecting the following "
          "system python's packages folders into sys.path: "+', '.join(injections)+f". This is not a "
          "solution, it's a hack. If you encounter exceptions using the workbench make sure to install the "
          "python dependencies in a proper way "+warningTextMid)
      except Exception:
        warnText = (warningTextBegin+"These package(s) were not importable even after injecting the following "
          "system python's packages folders into sys.path: "+', '.join(injections)+f". "+severeness
          +warningTextMid+"Last resort is the hacky way (3): install "
          "the before-mentioned python package(s) in your system python shell and hope for the best. "
          "Good luck!")
      warnText += '\n\n'+versionInfo(_returnText=True)+'\n\n'+'*'*80+'\n\n'
      def breakLine(l):
        res = []
        for w in l.split(' '):
          if len(' '.join(res).split('\n')[-1])+len(w) > 80:
            w = '\n'+w
          res.append(w)
        return ' '.join(res)
      warnText = '\n'.join([breakLine(l) for l in warnText.split('\n')])

      # emit warning immediately
      warnings.warn(warnText)

      # emit exception with delay to make it visible in the freecad GUI (if -c option is not present)
      if '-c' not in sys.argv:
        import threading
        def delayedWarn(sleep):
          import time
          time.sleep(sleep)
          raise ImportError(warnText)
        threading.Thread(target=delayedWarn, args=(2,), daemon=True).start()

# run on module load
_hackilyUpdateSysPathIfPythonDependenciesMissing()
