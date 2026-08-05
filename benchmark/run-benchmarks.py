from numpy import *
import optics_design_workbench
from optics_design_workbench.jupyter_utils import *
from optics_design_workbench.simulation import cpuCount
import os
import yaml

basedir = os.path.dirname(__file__)
results = 'benchmark-scores.yaml'

def main():
  # store version info
  versionInfo = optics_design_workbench.versionInfo(_returnText=True)

  # select all files to run benchmarks for
  files = [f for f in os.listdir(basedir) if f.endswith('.FCStd')]

  # select all freecad binaries to run benchmarks for
  binaries = ['FreeCAD', os.path.realpath(basedir+'/../latest-freecad.AppImage')]

  # select all worker count settings to run benchmarks for
  workerCounts = [2**i for i in range(10) if 2**i <= cpuCount()]

  # run simulations and calculate scores
  scores = []
  for file in files:
    for binary in binaries:
      for workerCount in workerCounts:
        # clear log if existing
        try:
          os.remove(f'{basedir}/{file[:-6]}.OpticsDesign/optics_design_workbench.log')
        except Exception:
          pass

        # extract rays per hour score from log file in background thread
        raysPerSecPerWorkerLog = []
        isRunning = True
        def collectRaysPerSecPerWorker():
          nonlocal isRunning
          prevLine = None
          while isRunning:
            time.sleep(90)
            with open(f'{basedir}/{file[:-6]}.OpticsDesign/optics_design_workbench.log') as _f:
              logText = _f.read().split('\n')
            raysPerSec = nan
            for line in reversed(logText):
              if line == prevLine:
                break
              if 'rays/s' in line and 'iterations done' in line:
                try:
                  raysPerSec = float(line.split('rays/s')[0].split()[-1])
                  prevLine = line
                  break
                except Exception:
                  pass
            print(f'{raysPerSec/workerCount=:.1e}')
            raysPerSecPerWorkerLog.append([time.time(), raysPerSec/workerCount])
        (t := threading.Thread(target=collectRaysPerSecPerWorker, daemon=True)).start()

        # start simulation
        print(f'starting benchmark with {file=}, {binary=}, {workerCount=}')
        setDefaultFreecadExecutable(binary)
        with FreecadDocument(file, showProgress=False) as f:
          f.cfg.WorkerProcessCount = f'{workerCount}'
          t0 = time.time()
          f.runSimulation('true', endIf=lambda r: time.time()-t0 > 30*60)
        isRunning = False
        t.join()

        # add to scores after job is done
        scores.append([time.time(), versionInfo, file, binary, workerCount, raysPerSecPerWorkerLog])
  print(f'dumping {len(scores)=}')

  # update results file on disk
  allScores = []
  if os.path.exists(basedir+'/'+results):
    with open(basedir+'/'+results, 'r') as _f:
      allScores = yaml.safe_load(_f)
  if type(allScores) is not list:
    allScores = []

  # add just calculated scores
  allScores = [scores]+allScores

  # update results on disk
  with open(basedir+'/'+results, 'w') as _f:
    _f.write(yaml.dump(allScores, default_flow_style=False))


if __name__ == '__main__':
  main()