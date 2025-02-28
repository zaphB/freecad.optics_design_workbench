#!/usr/bin/env python3

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *
from matplotlib.pyplot import *
import scipy.optimize

import unittest
import subprocess
import time
import os
import pickle
import shutil

FREECAD_BINARY = os.environ.get('TEST_FREECAD_BINARY', '/usr/bin/FreeCAD')


class TestRunNotebooks(unittest.TestCase):
  def _cleanResults(self, filename):
    baseDir = os.path.abspath(os.path.dirname(__file__))
    # remove results folder
    try:
      shutil.rmtree(baseDir+'/'+filename+'.OpticsDesign')
    except:
      pass

  def _runFile(self, filename, cleanup=True, cancelAfter=None, timeout=60*60):
    baseDir = os.path.abspath(os.path.dirname(__file__))

    # remove results folder
    if cleanup:
      try:
        shutil.rmtree(baseDir+'/'+filename+'.OpticsDesign')
      except:
        pass

    # run true simulation
    p = subprocess.Popen([FREECAD_BINARY, filename+'.FCStd', '-c'],
                          cwd=baseDir, 
                          #stdout=subprocess.DEVNULL,
                          #stderr=subprocess.DEVNULL,
                          stdin=subprocess.PIPE)

    try:
      # assemble python code to run
      pythonLines = []
      pythonLines.append('from freecad.optics_design_workbench import simulation')
      if cancelAfter is not None:
        pythonLines.append(f'import threading')
        pythonLines.append(f'import time')
        pythonLines.append(f'def delayedCancel():')
        pythonLines.append(f'  time.sleep({cancelAfter})')
        pythonLines.append(f'  simulation.runAction("stop")')
        pythonLines.append(f'')
        pythonLines.append(f'thr = threading.Thread(target=delayedCancel)')
        pythonLines.append(f'thr.start()')

      pythonLines.append('simulation.runAction("true")')

      p.stdin.write((
        '\r\n'.join(pythonLines)+'\r\nexit()\r\n'
      ).encode('utf8'))
      p.stdin.flush()

      # wait until process finishes
      t0 = time.time()
      while p.poll() is None:
        if time.time()-t0 > timeout:
          raise RuntimeError('freecad test process did not exit on time')
        time.sleep(.5)
    finally:
      p.stdin.close()
      time.sleep(1)
      if p.poll is None:
        p.kill()
        time.sleep(2)
        if p.poll is None:
          raise RuntimeError('failed killing freecad test process')

    # return paths
    return baseDir, filename


  def test_runPlaygroundExample(self):
    # make sure FCStd file runs and yields expected number of hits (> 100 rays * 10 iterations)
    baseDir, filename = self._runFile('playground')
    resultsPath = baseDir+'/'+filename+'.OpticsDesign/raw/simulation-run-000000/source-OpticalPointSource/object-OpticalAbsorberGroup'
    results = []
    for f in os.listdir(resultsPath):
      with open(resultsPath+'/'+f, 'rb') as _f:
        results.append(pickle.load(_f))
    totalHits = sum([len(r['points']) for r in results])
    self.assertGreater(totalHits, 99)
    self._cleanResults(filename)


  def _test_runWithoutSettingsObject(self):
    # make sure FCStd file without any settings can also run
    _, filename = self._runFile('nosettings')
    self._cleanResults(filename)

  def test_runAndCancelGaussianExample(self):
    t0 = time.time()
    baseDir, filename = self._runFile('gaussian', cancelAfter=5)



  def test_runGaussianExample(self):
    baseDir, filename = self._runFile('gaussian')

    # make sure results exist
    resultsPath = baseDir+'/'+filename+'.OpticsDesign/raw/simulation-run-000000/source-OpticalPointSource/object-OpticalAbsorberGroup'
    results = []
    for f in os.listdir(resultsPath):
      with open(resultsPath+'/'+f, 'rb') as _f:
        results.append(pickle.load(_f))
    totalHits = sum([len(r['points']) for r in results])
    self.assertGreater(totalHits, 1e4)

    # make sure result is perfect gaussian
    points = concatenate([r['points'] for r in results])[:,:2]
    figure()
    Hs, Xs, Ys, _ = hist2d(points[:,0], points[:,1], bins=30)
    savefig(baseDir+'/'+filename+'-gaussian-histogram.png')
    close()

    gaussian = lambda X, A, s, x0: A*exp(-(X-x0)**2/s**2)
    distance = 100
    thetaSigma = sqrt(1e-4)

    for i, (X, Y) in enumerate(
                [ ( (Xs[1:]+Xs[:-1])/2, Hs[argmin(abs(Ys)),:] ),
                  ( (Ys[1:]+Ys[:-1])/2, Hs[:,argmin(abs(Xs))] ) ]):
      figure()
      plot(X, Y, 'x')
      popt, _ = scipy.optimize.curve_fit(gaussian, X, Y, p0=(max(Y), 10, 0))
      Xlin = linspace(min(X), max(X), 300)
      Ylin = gaussian(Xlin, *popt)
      plot(Xlin, Ylin)
      plot(Xlin, gaussian(Xlin, max(Y), distance*thetaSigma, 0))
      savefig(baseDir+'/'+filename+f'-gaussian-crosssection-fit-{"xy"[i]}.pdf')
      close()
      #print(f'found sigma: {abs(popt[1]):.3f}, theoretical sigma: {distance*thetaSigma:.3f}')
      foundSigma = abs(popt[1])
      theoreticalSigma = distance*thetaSigma
      self.assertLess(abs(foundSigma-theoreticalSigma)/foundSigma, 50e-2)
      foundCenter = popt[-1]
      self.assertLess(abs(foundCenter), 50e-2)

    # cleanup
    self._cleanResults(filename)

  
  def test_runThreeTimes(self):
    # make sure working dir is clean
    baseDir, filename = self._runFile('playground')
    self._cleanResults(filename)

    # run simulation three times without cleaning
    for _ in range(3):
      baseDir, filename = self._runFile('playground', cleanup=False)
    
    # expect three result folders
    results = os.listdir(baseDir+'/'+filename+'.OpticsDesign/raw/')
    self.assertEqual(len(results), 3)

    # cleanup
    self._cleanResults(filename)


  def test_runAndCancelThreeTimes(self):
    # make sure working dir is clean
    baseDir, filename = self._runFile('gaussian', cancelAfter=3)
    self._cleanResults(filename)

    # run simulation three times without cleaning and cancel after a few seconds
    for _ in range(3):
      baseDir, filename = self._runFile('gaussian', cleanup=False, cancelAfter=3)
    
    # expect three result folders
    results = os.listdir(baseDir+'/'+filename+'.OpticsDesign/raw/')
    self.assertEqual(len(results), 3)

    # cleanup
    self._cleanResults(filename)


  def test_runFreecadNotebooks(self):
    baseDir = os.path.abspath(os.path.dirname(__file__))

    # find all notebooks and run them
    for root, dirs, files in os.walk(baseDir):
      for f in files:
        if 'notest' in f or 'notest' in root or 'checkpoint' in f or 'checkpoint' in root:
          continue
        if f.endswith('.ipynb') and not f.endswith('.nbconvert.ipynb'):
          with self.subTest(f):
            subprocess.run(f'uv run jupyter nbconvert --ExecutePreprocessor.timeout=None --to notebook --execute --inplace "{f}"',
                           cwd=root, shell=True, check=True)
