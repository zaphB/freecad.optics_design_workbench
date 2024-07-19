__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

'''.strip()


#!/usr/bin/env python3

import unittest
import subprocess
import time
import os
import shutil

FREECAD_BINARY = os.environ.get('TEST_FREECAD_BINARY', '/usr/bin/FreeCAD')

class TestRunNotebooks(unittest.TestCase):
  def _cleanResults(self, filename):
    baseDir = os.path.abspath(os.path.dirname(__file__))
    # remove results folder
    try:
      shutil.rmtree(baseDir+'/'+filename+'.opticalSimulationResults')
    except:
      pass

  def _run(self, fcOptions, pythonLines, timeout=5):
    baseDir = os.path.abspath(os.path.dirname(__file__))

    # run freecad in cli mode
    p = subprocess.Popen([FREECAD_BINARY, '-c', *fcOptions],
                          cwd=baseDir, 
                          #stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,
                          stdin=subprocess.PIPE)

    # pass python snippets via stdin
    p.stdin.write((
      '\r\n'.join(pythonLines)+'\r\n'
      'exit()\r\n'
    ).encode('utf8'))
    p.stdin.flush()

    # wait until process finishes
    t0 = time.time()
    def checkOutput():
      while output := p.stderr.readline().decode():
        output = output.strip()
        if output:
          print('stderr: ', output)
          if 'RuntimeError' in output:
            raise RuntimeError(output)
    try:
      while p.poll() is None:
        checkOutput()
        time.sleep(.5)
        if time.time()-t0 > timeout:
          raise RuntimeError('timed out')
    finally:
      p.stdin.close()
      p.terminate()
      p.kill()
      try:
        checkOutput()
      finally:
        p.stderr.close()

    # sleep until freecad process died
    t0 = time.time()
    while p.poll() is None:
      time.sleep(.5)
      if time.time()-t0 > 30:
        raise RuntimeError('timed out waiting for freecad to quit')

    # return paths
    return baseDir, p


  def test_unsavedFile(self):
    # create unsaved file and start continuous simulation
    for action in ('true', 'pseudo',):
      try:
        _, p = self._run([], [
          'from freecad.exp_optics_workbench import simulation',
          'App.newDocument()',
          f'simulation.runAction("{action}")'
        ])
      except RuntimeError as e:
        if 'not yet saved' not in str(e):
          raise
      else:
        raise RuntimeError('expected to fail with "unsaved file" error, but exited without error')


  def test_noWritePermissions(self):
    # open file in a folder without write permission and start simulation
    for action in ('true', 'pseudo',):
      try:
        _, p = self._run(['no-write-permission/playground.FCStd'],
          [
            'from freecad.exp_optics_workbench import simulation',
            f'simulation.runAction("{action}")'
          ])
      except RuntimeError as e:
        if 'is not writable' not in str(e):
          raise
      else:
        raise RuntimeError('expected to fail with "it seems directory is not writable" error, but exited without error')



if __name__ == '__main__':
  unittest.main()
