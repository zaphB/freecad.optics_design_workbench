__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

import subprocess
import os
import sys
import signal
import time
import random
import threading
import traceback

from ... import io
from .. import results_store
from .. import processes

_WORKER_INDEX = 0
_LAST_PRINTED_EXECUTABLE_PATH = 0

class WorkerProcess:
  '''
  This class represents one background process worker. It needs to known which
  simulation type is going on and which result folder to use and will run the 
  simulation_loop on its own.
  '''
  def __init__(self, isJupyterContext):
    # set index for worker process for easy identification in cli logs
    global _WORKER_INDEX, _LAST_PRINTED_EXECUTABLE_PATH
    self.index = _WORKER_INDEX
    _WORKER_INDEX += 1

    # store flag whether this worker was created in a jupyter context
    self.isJupyterContext = isJupyterContext

    # schedule end of life to circumvent FreeCAD memory leaks, schedule random
    # random lifetime to avoid synchronously killing and restarting all workers
    self.endOfLife = time.time() + (10+2*random.random())*60*60

    # try to extract freecad executable path: first check APPIMAGE environment variable,
    # to find out if running appimage, then try executable found in sys.executable,
    # if that does not look like a freecad executable let shell decide
    if freecadPath := os.environ.get('APPIMAGE', None):
      pass
    elif 'freecad' in sys.executable.lower():
      freecadPath = sys.executable
    else:
      freecadPath = 'FreeCAD'
    if time.time()-_LAST_PRINTED_EXECUTABLE_PATH > 60:
      io.verb(f'detected freecad executable "{freecadPath}"')
      _LAST_PRINTED_EXECUTABLE_PATH = time.time()

    # launch child process
    self._isRunning = True
    self._p = subprocess.Popen([freecadPath, '-c'],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE, 
                                text=True, bufsize=-1)

    # launch thread that keeps reading from the output and updates ring buffer
    self._stdioErrorCount = 0
    self._stdoutBufferLock = threading.RLock()
    self._stdoutBuffer = []
    def _readStdout():
      while self._stdioErrorCount <= 10:
        try:
          data = self._p.stdout.readline()
        except Exception:
          self._stdioErrorCount += 1
        else:
          if data.strip():
            with self._stdoutBufferLock:
              self._stdoutBuffer.append(data)
              self._stdoutBuffer[:] = self._stdoutBuffer[-100:]
          self._stdioErrorCount = 0
        # limit loop speed
        time.sleep(1e-2)
    self._stdoutReadThread = threading.Thread(target=_readStdout, daemon=True).start()

    # start thread that read stderr and forward to our stdout (only if more than
    # 10 lines are generated in a short time, indicating a stacktrace)
    def _readStderr():
      recentLines = []
      forward = False
      while self._stdioErrorCount <= 10:
        try:
          data = self._p.stderr.readline()
        except Exception:
          self._stdioErrorCount += 1
        else:
          data = data.replace('>>>', '')
          if data.strip():
            # keep buffer of lines of recent 2 seconds
            recentLines.append([time.time(), data])
            recentLines = [ (t,l) for t,l in recentLines if time.time()-t<2 ]

            if forward:
              try:
                self.say(data, level=io.err)
              except Exception:
                # just exit if self.say fails (happens e.g. if freecad is killed)
                return
              
              # clear buffer if not many lines have been printed recently
              if len(recentLines) <= 2:
                forward = False

            else:
              # set flag to flush if many error lines appeared recently
              if len(recentLines) >= 10:
                for t,l in recentLines:
                  self.say(l, level=io.err)
                forward = True

          self._stdioErrorCount = 0
        # limit loop speed
        time.sleep(1e-2)
    self._stderrReadThread = threading.Thread(target=_readStderr, daemon=True).start()

    self._isquit = False
    self._isterminate = False
    self._iskill = False
    self.wasLastBusy = time.time()

  def startSimulation(self, simulationType, simulationRunFolder):
    '''
    load file and start simulation
    '''
    self.simulationType = simulationType
    self.simulationFilePath = os.path.realpath(processes.simulatingDocument().getFileName())
    self.simulationRunFolder = simulationRunFolder
    self.wasLastBusy = time.time()

    # write python snippet to close all opened files, open required file, 
    # start desired simulation mode, and close all files again
    self.say('entering simulation loop...')
    self.write(f'\r\n'
               f'for doc in App.listDocuments():\r\n'
               f'  App.closeDocument(doc)'+'\r\n'*3+
               f'App.openDocument({repr(self.simulationFilePath)})\r\n'
               f'from freecad.optics_design_workbench import simulation\r\n'
               f'simulation.setIsJupyterContext({repr(self.isJupyterContext)})\r\n'
               f'simulation.runSimulation('
                      f'action={repr(self.simulationType)}, '
                      f'slaveInfo=dict(simulationRunFolder={repr(self.simulationRunFolder)}, '
                      f'               parentPid={os.getpid()}))\r\n'
               +f'\r\n'*3+
               f'for doc in App.listDocuments():\r\n'
               f'  App.closeDocument(doc)'+'\r\n'*3)

  def isBusy(self):
    from .. import freecad_elements
    with self._stdoutBufferLock:
      self._stdoutBuffer.clear()
    rn = f'{random.random()}'
    self.write(f'\r\n'
               f'print("{rn}")\r\n'
               f'\r\n')
    t0 = time.time()
    while True:
      with self._stdoutBufferLock:
        if rn in ''.join(self._stdoutBuffer):
          return False
      if time.time()-t0 > 2:
        self.wasLastBusy = time.time()
        return True
      # keep gui responsive
      freecad_elements.keepGuiResponsive()
      # limit loop speed
      time.sleep(1/50)

  def write(self, data):
    #self.say(f'writing {data=}')
    self._p.stdin.write(data)
    self._p.stdin.flush()

  def say(self, msg, level=io.info):
    if type(msg) is not str:
      msg = bytes(msg).decode('utf8')
    for line in msg.split('\n'):
      line = line.strip().strip('>').strip()
      if len(line):
        level(f'worker ({self.index}) says: '+line)

  def isRunning(self):
    if self._isRunning:
      if (res:=self._p.poll()) is not None:
        self._isRunning = False
        self.say(f'finished (exit code {res})')
    return self._isRunning

  def quit(self):
    if self.isRunning() and not self._isquit:
      self.say('asking FreeCAD to quit...')
      self._isquit = True

  def terminate(self):
    if self.isRunning():
      if not self._isterminate:
        self.say('terminating FreeCAD...')
        self._isterminate = True
      try:
        self._p.stdin.close()
      except:
        pass
      self._p.send_signal(signal.SIGTERM)

  def kill(self):
    if self.isRunning():
      if not self._iskill:
        self.say('killing FreeCAD...')
        self._iskill = True
      self._p.send_signal(signal.SIGKILL)
