__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

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
import uuid
import shutil
from atomicwrites import atomic_write

from .. import freecad_elements
from .. import io
from . import processes

GET_PROGRESS_LOCK = threading.RLock()

_README_TEXT = '''
# Optics Design Workbench project folder

This folder contains simulation results, analysis and optimizer notebooks
interacting with the Optics Design Workbench. Feel free to edit this readme
document your optics design project. If this readme is deleted, it will
be restored with its default content on the next simulation run.

Subfolders raw/simulation-run-xyz will be created on each simulation run
and contain the raw ray and hit information recorded during ray tracing. 

The subfolder notebooks/ contains all jupyter notebooks used to visualize,
analyze the results and to perform sweeps and optimizations of geometry
parameters.

The optics_design_workbench.log logfile will accumulate logging messages
generated during the ray tracing for debugging purposes.
'''.strip()

def getResultsFolderPath():
  base, fname, folderName = _getFolderBase()
  return f'{base}/{folderName}'

def getLatestRunIndex():
  folderName = getResultsFolderPath()+'/raw'
  if os.path.exists(folderName):
    safeInt = lambda x: int(x) if x.isnumeric() else -1 
    return max([safeInt(f[len('simulation-run-'):])
                            for f in os.listdir(folderName) 
                                    if f.startswith('simulation-run-')]
                  +[-1])
  return -1

def generateSimulationFolderName(index=None):
  if index is None:
    index = getLatestRunIndex()+1
  return f'raw/simulation-run-{int(index):06d}'

def getLatestRunFolderPath():
  index = getLatestRunIndex()
  if index < 0:
    return None
  return f'{getResultsFolderPath()}/{generateSimulationFolderName(index)}'

def _getFolderBase():
  # check whether current file is saved
  if not processes.simulatingDocument() or not processes.simulatingDocument().getFileName():
    raise RuntimeError('cannot start simulation because no active document '
                       'or active document is not yet saved')

  # generate paths
  base, fname = os.path.split(os.path.realpath(processes.simulatingDocument().getFileName()))
  if fname.lower().endswith('.fcstd'):
    fname = fname[:-6]
  folderName = f'{fname}.OpticsDesign'
  return base, fname, folderName


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
               endAfterIterations=inf, endAfterRays=inf, endAfterHits=inf):
    self.simulationType = simulationType

    self.flushEverySeconds = flushEverySeconds
    self.dumpProgressEverySeconds = dumpProgressEverySeconds

    # randomize start times to prevent synchronization of worker dumps
    self._lastFlush = time.time()+self.flushEverySeconds*random.random()
    self._lastDumpedProgress = time.time()+self.dumpProgressEverySeconds*random.random()
    self._latestProgressUpdate = time.time()
    self._lastMasterProgressDump = 0
    self._masterProgressDumpIdx = 0
    self._lastMsg = time.time()
    self.t0 = time.time()
    
    # split folder and file name and strip suffix to generate
    # basePath for this results object
    base, fname, folderName = _getFolderBase() 
    self.basePath = f'{base}/{folderName}'

    # set run folder name
    self.simulationRunFolder = simulationRunFolder

    # check whether paths are writable and mark run folder with random id to uniquely identify it in the future
    # if uid file already exists assume that this check can be skipped
    _path = f'{self.basePath}/{self.simulationRunFolder}'
    try:
      os.makedirs(_path, exist_ok=True)
      if not any([f.startswith('uid-') for f in os.listdir(_path)]):
        with open(f'{_path}/uid-{uuid.uuid4()}', 'w') as _f: 
          pass
    except Exception:
      raise RuntimeError(f'it seems simulation result path is not writable: {_path}')

    # set limitss
    self.endAfterIterations = endAfterIterations
    self.endAfterRays = endAfterRays
    self.endAfterHits = endAfterHits
    self.reachedEnd = False

    # counters for progress tracking
    self.totalIterations = 0
    self.totalTracedRays = 0
    self.totalRecordedRays = 0
    self.totalRecordedHits = 0
    self.progressByWorker = {}

    # prepare lists to store results
    self.rays = None
    self.hits = None

    # flag that is set to true when the simulation corresponding to this store is done
    self._cleanedUp = False

    # make sure the default folder structure exists, create it otherwise
    self._ensureFolderStructureExists()

  def _ensureFolderStructureExists(self):
    # create folders if not existing
    for expectPath in ['raw', 'notebooks']:
      os.makedirs(self.basePath+'/'+expectPath, exist_ok=True)

    # create readmes if not existing
    if not os.path.exists(self.basePath+'/README.md'):
      with atomic_write(self.basePath+'/README.md', mode='w') as f:
        f.write(_README_TEXT)

  def _raiseIfCleanedUp(self):
    if self._cleanedUp:
      raise RuntimeError(f'this storage was already cleaned up, cannot run requested method')

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
      folderName += f'/source-{source.Label}'
    if obj:
      folderName += f'/object-{obj.Label}'

    # generate filename from fingerprint, timestamp and kind
    fname = f'{self._fingerprint()}-{kind}.pkl'

    # make sure path exists and return
    os.makedirs(f'{self.basePath}/{folderName}', exist_ok=True)
    return f'{self.basePath}/{folderName}/{fname}'

  def flush(self):
    '''
    flush buffered data to disk and clear results lists
    '''
    # make sure instance was not yet cleaned up
    self._raiseIfCleanedUp()

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
      for source, obj, p, d, power, isEntering, metadata in self.hits:
        # create entry in results dict if needed
        fname = self._makeFilename(kind='hits', source=source, obj=obj)
        if fname not in results.keys():
          results[fname] = dict(source=source.Name, obj=obj.Name,
                                points=[], directions=[], 
                                powers=[], isEntering=[])

        # append data to entry
        results[fname]['points'].append(p)
        results[fname]['directions'].append(d)
        results[fname]['powers'].append(power)
        results[fname]['isEntering'].append(int(isEntering))

        # extend metadata entries, make sure length matches main data arrays
        currentLen = len(results[fname]['points'])-1
        for k, v in metadata.items():
          if k not in results[fname].keys():
            results[fname][k] = [nan]*currentLen
          if len(results[fname][k]) < currentLen:
            results[fname][k].extend([nan]*(currentLen-len(results[fname][k])))
          results[fname][k].append(v)

      # loop through create fnames, convert to numpy arrays and dump
      for fname, res in results.items():
        with open(fname, 'wb') as f:
          for k in res.keys():
            if type(res[k]) is list:
              # if nans exist, try to find a non-nan element. If that element has a 
              # shape, make sure nans are replaced by nan-arrays of the same shape
              if nan in res[k]:
                for _v in res[k]:
                  if not isnan(_v):
                    break
                if not isnan(_v) and len(shape(_v)):
                  for i in range(len(res[k])):
                    if isnan(res[k]):
                      res[k] = ones(shape(_v))*nan

              # try to convert to array and warn if it failed
              try:
                res[k] = array(res[k]) 
              except Exception:
                io.warn(f'failed to convert key {k} to array: {res[k]}')
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
    # make sure instance was not yet cleaned up
    self._raiseIfCleanedUp()

    # write progress atomically
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

  def getProgress(self, _neverReport=False):
    # if instance is cleaned up, just return latest reported progress value
    if self._cleanedUp:
      return getattr(self, '_lastReportedProgress', {})

    # make sure no other threads interfere
    with GET_PROGRESS_LOCK:
    
      # assemble result dictionary
      result = {}
      for _, prog in self.getProgressByWorker().items():
        for k, v in prog.items():
          if k not in result:
            result[k] = 0
          result[k] += v

      # check whether simulation is done and call cancelSimulation if so
      if (result.get('totalIterations', 0) > self.endAfterIterations
              or result.get('totalTracedRays', 0) > self.endAfterRays
              or result.get('totalRecordedHits', 0) > self.endAfterHits):
        self.reachedEnd = True
        processes.setIsFinished(True)

      # dump total progress to disk from time to time
      if processes.isMasterProcess() and time.time() - self._lastMasterProgressDump > .5:
        with atomic_write(f'{self.basePath}/{self.simulationRunFolder}/progress/master-{self._masterProgressDumpIdx:09d}', 
                          mode='wb', overwrite=True) as f:
          pickle.dump(dict(totalIterations = result.get('totalIterations', 0),
                           totalTracedRays = result.get('totalTracedRays', 0),
                           totalRecordedHits = result.get('totalRecordedHits', 0),
                           totalRecordedRays = result.get('totalRecordedRays', 0),
                           endAfterIterations = self.endAfterIterations,
                           endAfterRays = self.endAfterRays,
                           endAfterHits = self.endAfterHits), f)

        # remove master progress files older than 10s
        _i = 10
        while True:
          fname = f'{self.basePath}/{self.simulationRunFolder}/progress/master-{self._masterProgressDumpIdx-_i:09d}'
          if not os.path.exists(fname):
            break
          if time.time()-os.stat(fname).st_mtime > 10:
            os.remove(fname)
          _i += 1

        # update timer and index
        self._masterProgressDumpIdx += 1
        self._lastMasterProgressDump = time.time()

      # report progress to shell from time to time
      if time.time() - self._lastMsg > 60 and not _neverReport:
        iteration = result.get("totalIterations", 0) or 0
        io.info(f'{iteration} iterations done, '
                f'{processes.isWorkerRunning()} workers are alive, '
                f'{self.performanceDescription()}')
        self._lastMsg = time.time()

      self._lastReportedProgress = result
      return result

  def performanceDescription(self):
    # disable reporting to prevent endless recursion
    p = self.getProgress(_neverReport=True)
    return (f'{60*60*p.get("totalTracedRays", 0)/(time.time()-self.t0):.1e} rays/hour, '
            f'{60*60*p.get("totalRecordedHits", 0)/(time.time()-self.t0):.1e} recorded hits/hour')

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
    # make sure instance was not yet cleaned up
    self._raiseIfCleanedUp()

    # check if it is time to flush to disk
    if time.time()-self._lastFlush > self.flushEverySeconds:
      self.flush()

    # check if it is time to dump progress
    if time.time()-self._lastDumpedProgress > self.dumpProgressEverySeconds:
      self.dumpProgress()

      # if we are the master process, make sure to collect all slave progresses
      # from time to time
      if processes.isMasterProcess():
        self.getProgress()

  def isSimulationRunning(self):
    return processes.isRunning()
  
  def simulationEndedGracefully(self):
    return not processes.isRunning() and self.reachedEnd

  def addRay(self, source):
    # make sure instance was not yet cleaned up
    self._raiseIfCleanedUp()

    if self.rays is None:
      self.rays = []
    ray = SimulationResultsSingleRay(source)
    self.rays.append(ray)
    self.writeDiskIfNeeded()

    # return single ray results instance
    return ray

  def addRayHit(self, source, obj, point, direction, power, isEntering, metadata):
    # make sure instance was not yet cleaned up
    self._raiseIfCleanedUp()

    if self.hits is None:
      self.hits = []
    self.hits.append([source, obj, point, direction, power, isEntering, metadata])
    self.writeDiskIfNeeded()

  def cleanup(self):
    '''
    remove temp files of the result store generated during the simulation but 
    that are not part of the actual result 
    '''
    # remove progress tracking folder
    try:
      shutil.rmtree(self.progressMonitorPath())
    except Exception:
      io.warn(f'failed to cleanup progress monitoring path at "{self.progressMonitorPath()}"')

    # mark as done
    self._cleanedUp = True
