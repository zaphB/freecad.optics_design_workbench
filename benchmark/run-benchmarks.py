from optics_design_workbench.jupyter_utils import *
from optics_design_workbench.simulation_loop import cpuCount
import os
import yaml

basedir = os.path.basepath(__file__)
results = 'benchmark-scores.yaml'

def main():
  # select all files to run benchmarks for
  files = [f for f in oslistdir(basedir) if f.endswith('.FCStd')]

  # select all freecad binaries to run benchmarks for
  binaries = ['FreeCAD', basedir+'/../latest-freecad.AppImage']

  # select all worker count settings to run benchmarks for
  workerCounts = [2**i for i in range(10) if 2**i <= cpuCount()]

  # run simulations and calculate scores
  scores = []
  for file in files:
    for binary in binaries:
      for workerCount in workerCounts:
        
        


  # update results file on disk
  allScores = []
  if os.path.exists(basedir+'/'+results):
    with open(basedir+'/'+results, 'r') as _f:
      allScores = yaml.load(_f)

  # add just calculated scores
  allScores.append(scores)

  # update results on disk
  with open(basedir+'/'+results, 'f') as _f:
    yaml.dump(allScores, default_flow_style=False)
