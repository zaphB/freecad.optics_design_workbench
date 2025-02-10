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

from ... import io
from .. import results_store
from .. import processes

_WORKER_INDEX = 0

class WorkerProcess:
  '''
  This class represents one background process worker. It needs to known which
  simulation type is going on and which result folder to use and will run the 
  simulation_loop on its own.
  '''

  def __init__(self, simulationType, simulationRunFolder):
    # set index for worker process for easy identification in cli logs
    global _WORKER_INDEX
    self.index = _WORKER_INDEX
    _WORKER_INDEX += 1

    # start freecad in cli mode (-c) with current document as active document
    self.simulationType = simulationType
    self.simulationFilePath = os.path.realpath(processes.simulatingDocument().getFileName())
    self.simulationRunFolder = simulationRunFolder
    self._isRunning = True

    # try to extract freecad executable path: first check APPIMAGE environment variable,
    # to find out if running appimage, then try executable found in sys.executable,
    # if that does not look like a freecad executable let shell decide
    if freecadPath := os.environ.get('APPIMAGE', None):
      pass
    elif 'freecad' in sys.executable.lower():
      freecadPath = sys.executable
    else:
      freecadPath = 'FreeCAD'
    io.verb(f'detected freecad executable "{freecadPath}"')

    # launch child process
    self._p = subprocess.Popen([freecadPath, '-c', self.simulationFilePath],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                stdin=subprocess.PIPE, 
                                text=True, bufsize=-1)

    # write python snippet to start desired simulation mode
    self.say('entering simulation loop...')
    self.write(f'\r\n'
               f'import freecad.optics_design_workbench.simulation\r\n'
               f'freecad.optics_design_workbench.simulation.runSimulation('
                      f'action="{self.simulationType}", '
                      f'slaveInfo=dict(simulationRunFolder="{self.simulationRunFolder}", '
                      f'               parentPid={os.getpid()}))\r\n'
               f'exit()\r\n')

    self._isquit = False
    self._isterminate = False
    self._iskill = False

  def write(self, data):
    self._p.stdin.write(data)
    self._p.stdin.flush()

  def say(self, msg):
    if type(msg) is not str:
      msg = bytes(msg).decode('utf8')
    for line in msg.split('\n'):
      line = line.strip().strip('>').strip()
      if len(line):
        io.info(f'worker ({self.index}) says: '+line)

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
