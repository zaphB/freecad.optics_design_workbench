__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import pytest
import os

from optics_design_workbench import jupyter_utils

baseDir = os.path.abspath(os.path.dirname(__file__))

@pytest.fixture
def f():
  with jupyter_utils.FreecadDocument(f'{baseDir}/main.FCStd') as f:
    f.disableFastMode()
    yield f

@pytest.fixture(params=[-5, 0, 1, 2, 4, 'num_cpus'])
def numCpus(request):
  return request.param

def test_settingNumCpus(f, cfg, numCpus):
  cfg.WorkerProcessCount = numCpus
  if type(numCpus) is int:
    assert int(cfg.WorkerProcessCount.get()) == max([1, numCpus])

def test_configSwitching(f):
  for _ in range(3):
    f.cfg.Active = True
    assert f.sequentialCfg.Active.get() is False
    f.sequentialCfg.Active = True
    assert f.cfg.Active.get() is False

@pytest.fixture(params=['regular', 'sequential'])
def cfg(f, request):
  if request.param == 'regular':
    f.cfg.Active = True
    assert f.sequentialCfg.Active.get() is False
    yield f.cfg
  if request.param == 'sequential':
    f.sequentialCfg.Active = True
    assert f.cfg.Active.get() is False
    yield f.sequentialCfg

def test_simulationEndAfertHits(f, cfg, numCpus):
  cfg.WorkerProcessCount = numCpus
  cfg.EndAfterRays = 'inf'
  cfg.EndAfterHits = 1e3  
  r = f.runSimulation('true')
  print(f'{len(r.loadHits('*'))} rays hit the absorber')
  assert len(r.loadHits('*')) > 999

def test_simulationEndAfterRays(f, cfg, numCpus):
  cfg.WorkerProcessCount = numCpus
  cfg.EndAfterRays = 1e3
  cfg.EndAfterHits = 'inf'
  r = f.runSimulation('true')
  print(f'{len(r.loadHits('*'))} rays hit the absorber')
  assert len(r.loadHits('*')) > 100

def test_simulationEndIfCallback(f, cfg, numCpus):
  cfg.WorkerProcessCount = numCpus
  cfg.EndAfterRays = 'inf'
  cfg.EndAfterHits = 'inf'
  r = f.runSimulation('true', endIf=lambda r: len(r.loadHits('*'))>1e3 )
  print(f'{len(r.loadHits('*'))} rays hit the absorber')
  assert len(r.loadHits('*')) > 1e3
