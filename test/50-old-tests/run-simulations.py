#!/usr/bin/env python3

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


from numpy import *
from matplotlib.pyplot import *
import scipy.optimize

import pytest
import subprocess
import time
import os
import pickle
import shutil

FREECAD_BINARY = os.environ.get('TEST_FREECAD_BINARY', '/usr/bin/FreeCAD')

baseDir = os.path.abspath(os.path.dirname(__file__))

def _cleanupResults(filename):
  # remove raw result and log folders
  for folder in 'raw oldlogs'.split():
    try:
      shutil.rmtree(baseDir+'/'+filename+'.OpticsDesign/'+folder)
    except:
      pass
  for f in os.scandir(baseDir):
    if f.name.startswith(filename) and f.name.lower().endswith('.FCBak'):
      os.remove(baseDir+'/'+f)

def _runFile(filename, cleanup=True, cancelAfter=None, timeout=60*60):
  baseDir = os.path.abspath(os.path.dirname(__file__))
  # remove results folder
  if cleanup:
    _cleanupResults(filename)

  # run true simulation
  time.sleep(10)
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

  # remove FCBak files after running
  for f in os.scandir(baseDir):
    if f.name.startswith(filename) and f.name.lower().endswith('.FCBak'):
      os.remove(baseDir+'/'+f)

  # return paths
  return baseDir, filename


def test_runPlaygroundExample():
  # make sure FCStd file runs and yields expected number of hits (> 100 rays * 10 iterations)
  baseDir, filename = _runFile('playground')
  resultsPath = baseDir+'/'+filename+'.OpticsDesign/raw/simulation-run-000000/source-OpticalPointSource/object-OpticalAbsorberGroup'
  results = []
  for f in os.listdir(resultsPath):
    with open(resultsPath+'/'+f, 'rb') as _f:
      from optics_design_workbench import io
      results.append(io.unpickle(_f))
  totalHits = sum([len(r['points']) for r in results])
  assert totalHits > 99
  _cleanupResults(filename)


def _test_runWithoutSettingsObject():
  # make sure FCStd file without any settings can also run
  _, filename = _runFile('nosettings')
  _cleanupResults(filename)

def test_runAndCancelGaussianExample():
  t0 = time.time()
  baseDir, filename = _runFile('gaussian', cancelAfter=5)


def test_runGaussianExample():
  baseDir, filename = _runFile('gaussian')

  r = baseDir+'/gaussian.OpticsDesign/raw'
  #r = 'replay.OpticsDesign/raw'
  run = [f for f in sorted(os.listdir(r)) if os.path.isdir(f'{r}/{f}')][-1]
  resultsPath = f'{r}/{run}/source-OpticalPointSource/object-OpticalAbsorberGroup'

  # make sure results exist
  results = []
  for f in os.listdir(resultsPath):
    with open(resultsPath+'/'+f, 'rb') as _f:
      from optics_design_workbench import io
      results.append(io.unpickle(_f))
  totalHits = sum([len(r['points']) for r in results])
  assert totalHits > .8e5

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
    figure(figsize=(5,2.5))
    plot(X, Y, 'x')
    popt, _ = scipy.optimize.curve_fit(gaussian, X, Y, p0=(max(Y), 10, 0))
    Xlin = linspace(min(X), max(X), 300)
    Ylin = gaussian(Xlin, *popt)
    plot(Xlin, Ylin)
    plot(Xlin, gaussian(Xlin, max(Y), distance*thetaSigma, 0))
    savefig(baseDir+'/'+filename+f'-gaussian-crosssection-fit-{"xy"[i]}.pdf')
    close()
    #print(f'found sigma: {abs(popt[1]):.3f}, theoretical sigma: {distance*thetaSigma:.3f}')

    # make sure sigma is as expected
    foundSigma = abs(popt[1])
    theoreticalSigma = distance*thetaSigma
    assert abs(foundSigma-theoreticalSigma)/foundSigma < 0.3

    # make sure gaussian is nicely centered
    foundCenter = popt[-1]
    assert abs(foundCenter) < 0.3

  # cleanup
  _cleanupResults(filename)


def test_runThreeTimes():
  # make sure working dir is clean
  baseDir, filename = _runFile('playground')
  _cleanupResults(filename)

  # run simulation three times without cleaning
  for _ in range(3):
    baseDir, filename = _runFile('playground', cleanup=False)
  
  # expect three result folders
  results = os.listdir(baseDir+'/'+filename+'.OpticsDesign/raw/')
  assert len(results) == 3

  # cleanup
  _cleanupResults(filename)


def test_runAndCancelThreeTimes():
  # make sure working dir is clean
  baseDir, filename = _runFile('gaussian', cancelAfter=3)
  _cleanupResults(filename)

  # run simulation three times without cleaning and cancel after a few seconds
  for _ in range(3):
    baseDir, filename = _runFile('gaussian', cleanup=False, cancelAfter=3)
  
  # expect three result folders
  results = os.listdir(baseDir+'/'+filename+'.OpticsDesign/raw/')
  assert len(results) == 3

  # cleanup
  _cleanupResults(filename)


# run and simulate every file in folder for a short moment

def collectAllFCStd():
  for root, dirs, files in os.walk(baseDir):
    for _f in files:
      f = (root+'/'+_f)[len(baseDir):].lstrip('/')
      if 'notest' in f or 'notest' in root or 'checkpoint' in f or 'checkpoint' in root:
        continue
      if _f.endswith('.FCStd'):
        yield root, f, _f

allArgs = list(collectAllFCStd())
@pytest.mark.parametrize('args', allArgs, ids=[a[1] for a in allArgs])
def test_brieflyRunFCStdFiles(args):
  root, f, _f = args
  print(f'running simulation {f}')
  baseDir, filename = _runFile(f, cancelAfter=180)
  _cleanupResults(filename)


# run all notebooks 

def collectNotebooks():
  # find all notebooks
  for root, dirs, files in os.walk(baseDir):
    for _f in files:
      f = (root+'/'+_f)[len(baseDir):].lstrip('/')
      if 'notest' in f or 'notest' in root or 'checkpoint' in f or 'checkpoint' in root:
        continue
      if _f.endswith('.ipynb') and '.nbconvert' not in _f:
        yield root, f, _f

allArgs = list(collectNotebooks())
@pytest.mark.parametrize('args', allArgs, ids=[a[1] for a in allArgs])
def test_runFreecadNotebooks(args):
  root, f, _f = args
  print(f'running notebook {f}')
  try:
    subprocess.run(f'uv run jupyter nbconvert --ExecutePreprocessor.timeout=None '
                    f'--to notebook --execute "{_f}"',
                    cwd=root, shell=True, check=True)
  except Exception:
    raise
  else:    
    # do cleanup
    resultFile = root+'/'+_f[:-6]+'.nbconvert.ipynb'
    print(f'deleting {resultFile}...')
    os.remove(resultFile)
