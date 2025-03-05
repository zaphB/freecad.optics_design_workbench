__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

try:
  import FreeCADGui as Gui
  import FreeCAD as App
  from FreeCAD import Vector, Rotation
  import Part
except ImportError:
  pass

from numpy import *
import tempfile
import os
import random
import functools
import pickle
import shutil

from .generic_source import *
from .common import *
from . import ray
from . import find
from .. import io
from .. import simulation


#####################################################################################################
class ReplaySourceProxy(GenericSourceProxy):

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''

  def onInitializeSimulation(self, obj, state, ident):
    # reset iterator to make all rays in stock available again
    self._yieldOriginDirectionWavelengthPower.cache_clear()

    # delete temp folder used for flag files to mark datafiles as consumed
    if state == 'pre-worker-launch' and ident == 'master':
      if os.path.exists(self.flagfiledir()):
        shutil.rmtree(self.flagfiledir())

  def onExitSimulation(self, obj, ident):
    # clear folder after simulation is done
    if ident == 'master':
      if os.path.exists(self.flagfiledir()):
        shutil.rmtree(self.flagfiledir())


  def flagfiledir(self):
    return f'{simulation.getResultsFolderPath()}/replay-source-used-files'

  def _isFileConsumed(self, obj, path):
    # find path of requested file relative to replay dir
    relpath = os.path.relpath(path, obj.ReplayFromDir)

    # map path to flagfile path, check whether it exists and create flag
    # if not the case
    flagpath = f'{self.flagfiledir()}/{relpath}'
    os.makedirs(os.path.dirname(flagpath), exist_ok=True)
    if not (consumed := os.path.exists(flagpath)):
      with open(flagpath, 'w') as _:
        pass
    return consumed


  @functools.cache
  def _yieldOriginDirectionWavelengthPower(self, obj):
    '''
    This generator yields (origin, direction, wavelength, power) tuples of all rays recorded
    on disk in randomized order. The functools.cache decorator makes sure every result is 
    only yielded once. Calling the cache_clear method resets the generator. 
    '''
    if not obj.ReplayFromDir:
      raise RuntimeError(f'please set a replay directory for light source {obj.Name} '
                         f'(Data -> Optical Emission -> Replay From Dir)')

    if not os.path.exists(obj.ReplayFromDir):
      raise RuntimeError(f'selected replay directory of light source {obj.Name} does not '
                         f'seem to exist: {obj.ReplayFromDir} ')

    io.verb(f'starting replay source iterator')
    foundHitsFile = False
    for r, ds, fs in os.walk(obj.ReplayFromDir, topdown=True):
      # go through files in random order
      random.shuffle(fs)
      random.shuffle(ds)
      for f in fs:
        if f.endswith('-hits.pkl'):
          foundHitsFile = True
          if not self._isFileConsumed(obj, f'{r}/{f}'):
            data = {}
            with open(f'{r}/{f}', 'rb') as _f:
              data = pickle.load(_f)
            indices = list(range(len(data['powers'])))
            random.shuffle(indices)
            for i in indices:
              _wavelength = 1
              if len(data.get('wavelength', [])) > i:
                _wavelength = data['wavelength'][i]
              yield (data['points'][i], data['directions'][i], 
                     _wavelength, data['powers'][i])

    # raise if not a single good datafile was found
    if not foundHitsFile:
      raise RuntimeError(f'selected replay directory of light source {obj.Name} does not '
                         f'seem to contain any ray hit datafile: {obj.ReplayFromDir} ')


  def _generateRays(self, obj, mode, **kwargs):
    '''
    This generator yields each ray to be traced for one simulation iteration.
    '''
    # make sure GUI does not freeze
    keepGuiResponsiveAndRaiseIfSimulationDone()

    # determine number of rays to place
    raysPerIteration = 100
    if settings := find.activeSimulationSettings():
      raysPerIteration = settings.RaysPerIteration
    raysPerIteration *= obj.RaysPerIterationScale

    # fan-mode: replay lightsource does not support rendering fans
    if mode == 'fans':
      io.info(f'replay light source {obj.Name} does not support ray fans and '
              f'will not place any rays.')
      return []

    # true/pseudo random mode: place rays from stored file on disk in random order until none are left
    elif mode == 'true' or mode == 'pseudo':

      # warn that pseudo random mode is not supported and behaves identical to true random
      if mode == 'pseudo':
        io.warn(f'ReplaySource does not support pseudo-random mode and behaves identical to true-random mode')

      rayCount = 0
      gpM, gpMi = self._makeRayCache(obj)[:2]

      for origin, direction, wavelength, power in self._yieldOriginDirectionWavelengthPower(obj):
        # apply placement of lightsource to coordinates
        p1, p2 = gpM*App.Vector(origin), gpM*App.Vector(origin+direction)
        gorigin = p1
        gdirection = p2-p1

        # yield created ray
        yield ray.Ray(obj, gorigin, gdirection, wavelength=wavelength, initPower=power)

        # make sure to exit if enough rays for this iteration were placed
        rayCount += 1
        if rayCount >= raysPerIteration:
          return

      io.warn(f'replay light source {obj.Name} ran out of rays, canceling simulation...')
      raise SimulationEnded()

    else:
      raise ValueError(f'unexpected ray placement mode {mode}')


#####################################################################################################
class ReplaySourceViewProxy(GenericSourceViewProxy):
  pass
  
#####################################################################################################
class AddReplaySource(AddGenericSource):

  def Activated(self):
    # create new feature python object
    obj = App.activeDocument().addObject('App::LinkGroupPython', 'OpticalReplaySource')

    # create properties of object
    for section, entries in [
      ('OpticalEmission', [
        ('ReplayFromDir', '', 'Path', 'Select a hit coordinate file generated by another '
            'simulation to replay the ray hits with this light source.'),
      ]),
      ('OpticalSimulationSettings', [
        *self.defaultSimulationSettings(obj)
      ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = ReplaySourceProxy()
    if App.GuiUp:
      obj.ViewObject.Proxy = ReplaySourceViewProxy()

    return obj

  def GetResources(self):
    return dict(Pixmap=self.iconpath(),
                Accel='',
                MenuText='Make replay source',
                ToolTip='Add a replay light source to the current project.')

def loadReplaySource():
  Gui.addCommand('Add replay source', AddReplaySource())
