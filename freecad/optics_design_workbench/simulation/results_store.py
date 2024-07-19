__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

'''.strip()


try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

from numpy import *
import os
import time
import pickle
import functools
import threading
from atomicwrites import atomic_write

from .. import freecad_elements
from . import processes

def getResultsFolderPath():
  base, fname, folderName = _getFolderBase()
  return f'{base}/{folderName}'

def _getFolderBase():
  # check whether current file is saved
  if not App.activeDocument() or not App.activeDocument().getFileName():
    raise RuntimeError('cannot start simulation because no active document '
                       'or active document is not yet saved')

  # generate paths
  base, fname = os.path.split(os.path.realpath(App.activeDocument().getFileName()))
  if fname.lower().endswith('.fcstd'):
    fname = fname[:-6]
  folderNamePattern = '{projectName}.opticalSimulationResults'
  if settings := freecad_elements.find.activeSimulationSettings():
    folderNamePattern = settings.SimulationDataFolder
  folderName = time.strftime(folderNamePattern).format(
                                    projectName=fname, 
                                    settingsName=settings.Name if settings else 'defaultSettings')
  # return results
  return base, fname, folderName

def placeJobDoneFile(simulationRunFolder):
  with open(f'{getResultsFolderPath()}/{simulationRunFolder}/job-is-done', 'w') as _:
    pass

def jobDoneFileExists(simulationRunFolder):
  return os.path.exists(f'{getResultsFolderPath()}/{simulationRunFolder}/job-is-done')

class SimulationResultsSingleRay:
  def __init__(self, source):
    self.source = source
    self.isComplete = False
    self.segments = []

  def addSegment(self, points, power, medium):
    self.segments.append([points, power, medium])

  def dump(self, force=False):
    if not force and not self.isComplete:
      raise RuntimeError('trying to dump incomplete ray, this is not a good idea')

    if len(self.segments):
      # generate array of all point coordinates by taking all segment start
      # points and append the end point of the last segment
      pointArray = array([list(p) for (p,_), _, _ in self.segments]
                                                  + [self.segments[-1][0][1]])
      # generate array of all powers in segments
      powerArray = array([power for _,power,_ in self.segments])                                                  
      # generate string list of all media traversed by segments
      mediaList = [medium.Name if medium is not None else None for _,_,medium in self.segments]
      # return result dict
      return dict(points=pointArray, 
                  powers=powerArray,
                  media=mediaList)

  def rayComplete(self):
    self.isComplete = True


class SimulationResults:
  def __init__(self, simulationType, simulationRunFolder, flushEverySeconds=5, 
               dumpProgressEverySeconds=.2,
               maxIterations=inf, maxRays=inf, maxHits=inf):
    self.simulationType = simulationType

    self.flushEverySeconds = flushEverySeconds
    self.dumpProgressEverySeconds = dumpProgressEverySeconds

    # randomize start times to prevent synchronization of worker dumps
    self._lastFlush = time.time()+self.flushEverySeconds*random.random()
    self._lastDumpedProgress = time.time()+self.dumpProgressEverySeconds*random.random()
    self._latestProgressUpdate = time.time()
    self._lastMsg = time.time()
    self.t0 = time.time()
    
    # split folder and file name and strip suffix to generate
    # basePath for this results object
    base, fname, folderName = _getFolderBase() 
    self.basePath = f'{base}/{folderName}'

    # set run folder name
    self.simulationRunFolder = simulationRunFolder

    # check whether paths are writable
    try:
      os.makedirs(f'{self.basePath}/{self.simulationRunFolder}/.permission-check', exist_ok=True)
    except Exception:
      raise RuntimeError(f'it seems simulation result path is not writable: {self.basePath}/{self.simulationRunFolder}')
    finally:
      try:
        os.rmdir(f'{self.basePath}/{self.simulationRunFolder}/.permission-check')
        try:
          os.rmdir(f'{self.basePath}/{self.simulationRunFolder}')
        except Exception: pass
      except Exception: pass

    # set limitss
    self.maxIterations = maxIterations
    self.maxRays = maxRays
    self.maxHits = maxHits
    self.reachedMax = False

    # counters for progress tracking
    self.totalIterations = 0
    self.totalTracedRays = 0
    self.totalRecordedRays = 0
    self.totalRecordedHits = 0
    self.progressByWorker = {}

    # prepare lists to store results
    self.rays = None
    self.hits = None

  def incrementRayCount(self):
    self.totalTracedRays += 1

  def incrementIterationCount(self):
    self.totalIterations += 1

  @functools.cache
  def _fingerprint(self):
    return f'{int(time.time()*1e3)}-pid{os.getpid()}-thread{threading.get_ident()}'

  def _makeFilename(self, kind, source=None, obj=None):
    # group data by source and by hit element
    folderName = f'{self.simulationRunFolder}'
    if type(source) is str:
      folderName += f'/{source}'
    elif source:
      folderName += f'/lightsource-{source.Label}'
    if obj:
      folderName += f'/hitObject-{obj.Label}'

    # generate filename from fingerprint, timestamp and kind
    fname = f'{self._fingerprint()}-{kind}.pkl'

    # make sure path exists and return
    os.makedirs(f'{self.basePath}/{folderName}', exist_ok=True)
    return f'{self.basePath}/{folderName}/{fname}'

  def flush(self):
    '''
    flush buffered data to disk and clear results lists
    '''
    # reset fingerprint cache to make sure a fresh one is generated
    self._fingerprint.cache_clear()

    # handle ray data
    if self.rays is not None:
      # assemble dictionaries to dump
      results = {}

      # dump complete rays and store incomplete in separate list
      incomplete = []
      dump = []
      for r in self.rays:
        if r.isComplete:
          fname = self._makeFilename(kind='rays', source=r.source)
          if fname not in results.keys():
            results[fname] = []
          results[fname].append(r.dump())
        else:
          incomplete.append(r)

      # write result data
      for fname, dump in results.items():
        with open(fname, 'wb') as f:
          pickle.dump(dump, f)
        
      # replace internal ray list with incomplete list
      self.totalRecordedRays += len(self.rays or [])-len(incomplete or [])
      self.rays = incomplete if len(incomplete) else None

    # handle hit data
    if self.hits is not None:
      # assemble dictionaries to dump
      results = {}
      for source, obj, p, power, isEntering in self.hits:
        # create entry in results dict if needed
        fname = self._makeFilename(kind='hits', source=source, obj=obj)
        if fname not in results.keys():
          results[fname] = dict(source=source.Name, obj=obj.Name,
                                points=[], powers=[], isEntering=[])

        # append data to entry
        results[fname]['points'].append(list(p))
        results[fname]['powers'].append(power)
        results[fname]['isEntering'].append(int(isEntering))

      # loop through create fnames, convert to numpy arrays and dump
      for fname, res in results.items():
        with open(fname, 'wb') as f:
          for k in 'points powers isEntering'.split():
            res[k] = array(res[k]) 
          pickle.dump(res, f)

      # clear list
      self.totalRecordedHits += len(self.hits or [])
      self.hits = None

    # update last flush timestamp, add 10%ish random jitter to prevent synchronization of worker dumps
    self._lastFlush = time.time() + (.1*random.random()-.05)*self.flushEverySeconds

  def dumpProgress(self):
    '''
    dump pickled summary of simulation progress (use atomic_write)
    '''
    with atomic_write(self._makeFilename(source='progress', kind=str(hex(int(random.random()*1e15)))[2:]), 
                      mode='wb', overwrite=True) as f:
      pickle.dump(dict(totalIterations = self.totalIterations,
                       totalTracedRays = self.totalTracedRays,
                       totalRecordedHits = self.totalRecordedHits+len(self.hits or []),
                       totalRecordedRays = self.totalRecordedRays+len(self.rays or [])), f)

    # update last dump timestamp, add 100% random jitter to prevent synchronization of worker dumps
    self._lastDumpedProgress = time.time() + (2*random.random()-1)*self.dumpProgressEverySeconds
    self._latestProgressUpdate = time.time()

  @functools.cache
  def progressMonitorPath(self):
    return os.path.dirname(self._makeFilename(source='progress', kind='none'))

  def getProgress(self):
    result = {}
    for _, prog in self.getProgressByWorker().items():
      for k, v in prog.items():
        if k not in result:
          result[k] = 0
        result[k] += v

    # check whether simulation is done and call cancelSimulation if so
    if (result.get('totalIterations', 0) > self.maxIterations
            or result.get('totalTracedRays', 0) > self.maxRays
            or result.get('totalRecordedHits', 0) > self.maxHits):
      self.reachedMax = True
      processes.cancelSimulation()

    # report progress to shell from time to time
    if time.time() - self._lastMsg > 5:
      iteration = result.get("totalIterations") or 0
      processes.logMsg(f'current iteration {iteration} '
                       f'({60*60*iteration/(time.time()-self.t0):.1e} iters/hour), '
                       f'{processes.isWorkerRunning()} workers are alive')
      self._lastMsg = time.time()

    return result

  def getProgressByWorker(self):
    # find all files in progress dir
    monitorPath = self.progressMonitorPath()
    allFiles = os.listdir(monitorPath)

    # group files by worker processes
    byWorker = {}
    for f in allFiles:
      try:
        timestamp, pid, thread, randomHash = f.split('-')
      except Exception:
        pass
      else:
        key = pid
        if key not in byWorker.keys():
          byWorker[key] = []
        byWorker[key].append([timestamp, f])

    # update state according to latest file, delete all files afterwards
    for pid, files in byWorker.items():
      if len(files):
        # load latest progress
        progress = None
        for candidate in sorted(files, key=lambda e: -int(e[0])):
          latestFile = candidate[1]
          try:
            with open(monitorPath+'/'+latestFile, 'rb') as f:
              progress = pickle.load(f)
          except Exception:
            pass
          if progress:
            break

        # update window state
        if progress and type(progress) is dict:
          if pid not in self.progressByWorker.keys():
            self.progressByWorker[pid] = {}
          self.progressByWorker[pid].update(progress)

        # delete all files
        for f in files:
          os.remove(monitorPath+'/'+f[1])

        # note current time as latest update
        self._latestProgressUpdate = time.time()
    return self.progressByWorker

  def writeDiskIfNeeded(self):
    # check if it is time to flush to disk
    if time.time()-self._lastFlush > self.flushEverySeconds:
      self.flush()

    # check if it is time to dump progress
    if time.time()-self._lastDumpedProgress > self.dumpProgressEverySeconds:
      self.dumpProgress()

  def isSimulationRunning(self):
    return processes.isRunning() and time.time()-self._latestProgressUpdate < 10+10*self.dumpProgressEverySeconds

  def simulationEndedGracefully(self):
    return not processes.isRunning() and self.reachedMax

  def addRay(self, source):
    if self.rays is None:
      self.rays = []
    ray = SimulationResultsSingleRay(source)
    self.rays.append(ray)
    self.writeDiskIfNeeded()

    # return single ray results instance
    return ray

  def addRayHit(self, source, obj, point, power, isEntering):
    if self.hits is None:
      self.hits = []
    self.hits.append([source, obj, point, power, isEntering])
    self.writeDiskIfNeeded()

def getLatestRunIndex():
  folderName = getResultsFolderPath()
  if os.path.exists(folderName):
    safeInt = lambda x: int(x) if x.isnumeric() else -1 
    return max([safeInt(f[4:-4]) for f in os.listdir(folderName) 
                                    if f.startswith('run-')
                                          and f.endswith('-raw')]
                  +[-1])
  return -1

def generateSimulationFolderName(index=None):
  if index is None:
    index = getLatestRunIndex()+1
  return f'run-{int(index):04d}-raw'
