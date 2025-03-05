__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

from . import find
from .common import *
from .. import simulation

#####################################################################################################
class SimulationSettingsProxy():
  '''
  Proxy of the point point source object responsible for the logic
  '''
  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''

  def onChanged(self, obj, prop):
    # sync Visible property with active property to allow
    # convenient spacebar toggling of active settings
    if prop == 'Visibility':
      if not obj.Visibility and obj.Active:
        obj.Visibility = True

      # only set if not equal to prevent recursion
      if obj.Active != obj.Visibility:
        obj.Active = obj.Visibility

      # copy visibility to view obj (check truth value because ViewObjects 
      # do not exist in cli mode)
      if obj.ViewObject:
        obj.ViewObject.Visibility = obj.Visibility

    if prop == 'Active':
      # only set if not equal to prevent recursion
      if obj.Visibility != obj.Active:
        obj.Visibility = obj.Active

    if prop == 'Active' and obj.Active:
      # always cancel if active settings object was changed
      for settings in find.simulationSettings():
        if settings != obj:
          settings.Active = False

    # sanitize worker count
    if prop == 'WorkerProcessCount':
      if obj.WorkerProcessCount != 'num_cpus':        
        # set to default if non-integer input was found
        count = None
        try:
          count = int(obj.WorkerProcessCount)
        except ValueError:
          obj.WorkerProcessCount = 'num_cpus'

        # limit mit to 1
        if count and count < 1:
          obj.WorkerProcessCount = str(1)
        
        # limit count to 10 times cpu count + 10 (which would never make any sense)
        if count and count > 10 + 10*simulation.cpuCount():
          obj.WorkerProcessCount = str(int(10*simulation.cpuCount()))
    
    # sanitize EndAfter settings
    if prop.startswith('EndAfter'):
      val = getattr(obj, prop)
      if val != 'inf':
        try:
          val = int(round(float(val)))
        except ValueError:
          setattr(obj, prop, 'inf')
        else:
          # limit to positive numbers
          if val < 0:
            setattr(obj, prop, '1')

    # sanitize DistanceTolerance
    if prop == 'DistanceTolerance':
      val = getattr(obj, prop)
      try:
        val = float(val)
      except ValueError:
        setattr(obj, prop, '0.01')
      else:
        # limit range
        if val < 1e-12:
          setattr(obj, prop, '1e-12')

    # if sequential mode objects are altered, make sure empties are removed
    if 'SequentialMode' in prop:
      self.getTracingSequence(obj)


  def getTracingSequence(self, obj):
    if not obj.SequentialMode:
      return []
    sequence = []
    onlyUnsetSoFar = True
    hasEmpty = False
    lastUnset = 100
    for i in reversed(range(100)):
      attr = getattr(obj, f'SequentialModeElement{i:02d}', 'unset')
      if not len(attr):
        hasEmpty = True
      else:
        # find last unset index
        if attr == 'unset' and onlyUnsetSoFar:
          lastUnset = i
        else:
          onlyUnsetSoFar = False
        # assemble sequence
        if attr and attr != 'unset':
          sequence.append(attr)
    
    # add property for last unset
    if not hasEmpty and lastUnset < 100:
      obj.addProperty('App::PropertyLinkList', f'SequentialModeElement{lastUnset:02d}', 
                      'OpticalSimulationPerformanceSettings', 
                      f'List to specify order of optical elements to '
                      f'consider during ray tracing. Rays will not collide with anything but the next object '
                      f'given in the sequence. This can cause a massive speedup. Empty list implies the non-'
                      f'sequential mode, i.e. rays can collide with any optical object in the project.')

    return list(reversed(sequence))

#####################################################################################################
class SimulationSettingsViewProxy():
  '''
  Proxy of the point point source object responsible for the view
  '''
  def __init__(self, obj):
    self.objectName = obj.Name

  def getIcon(self):
    '''Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown.'''
    if App.activeDocument().getObject(self.objectName).Active:
      return find.iconpath('settings') 
    return find.iconpath('settings-inactive') 

  def onDelete(self, obj, subelements):
    '''Here we can do something when the feature will be deleted'''
    return True


  
#####################################################################################################
class MakeSimulationSettings:
  def Activated(self):
    # create mirror object
    obj = App.activeDocument().addObject('Part::FeaturePython', f'OpticalSimulationSettings')

    # create properties of object
    for section, entries in [
      ('OpticalSimulationSettings', [
        ('Active', True, 'Bool', 'Use these settings as simulation settings.'),
        ('EnableStoreSingleShotData', False, 'Bool', 'Store rays and hits to disk for every single-shot '
              'simulation.'),
      ]),
      ('OpticalSimulationPerformanceSettings', [
        ('EndAfterIterations', 'inf', 'String', 'Number of iterations after which simulation should stop'),
        ('EndAfterRays', '1e4', 'String', 'Number of traced rays after which simulation should stop'),
        ('EndAfterHits', 'inf', 'String', 'Number of recorded hits after which simulation should stop'),
        ('RaysPerIteration', 100, 'Float', 'Number of rays to place per simulation iteration for random '
              'and pseudo random modes.'),
        ('MaxIntersections', 100, 'Float', 'Maximum number of intersections (reflections/refractions/'
              'detections) that a ray may have with optical objects.'),
        ('DistanceTolerance', '0.01', 'String', 'If a ray is closer to a surface than this tolerance, '
              'it is considered to intersect with the surface.'),
        ('MaxRayLength', 1000, 'Float', 'Maximum length of each ray segment, i.e. the total ray length '
              'may be up to MaxIntersections*MaxRayLength. This is not a strict '
              'limit but rather a possibility for the ray tracer to save time by ignoring '
              'objects that are farther away from a given ray origin than this limit. Longer ray '
              'segments may still occur.'),
        ('ShowRaysInContinuousMode', True, 'Bool', 'Allows to switch of displaying rays in '
              'continuous simulation modes to speed up the calculation.'),
        ('WorkerProcessCount', 'num_cpus', 'String', 'Number of worker processes to spawn for continuous '
              f'simulation modes. Should be an integer or "num_cpus" ( = {simulation.cpuCount()} ).'),
        ('SequentialMode', False, 'Bool', 'Enable/disable sequential ray-tracing mode. In '
              f'sequential mode, rays will not collide with anything but the next object '
              f'given in the sequence. This can cause a massive speedup. Empty list implies the non-'
              f'sequential mode, i.e. rays can collide with any optical object in the project.'),
        ('SequentialModeElement00', None, 'LinkList', 'List to specify order of optical elements to '
              f'consider during ray tracing. Rays will not collide with anything but the next object '
              f'given in the sequence. This can cause a massive speedup. Empty list implies the non-'
              f'sequential mode, i.e. rays can collide with any optical object in the project.'),
      ]),
      ('OpticalSimulationMetadataSettings', [
        ('StoreHitInitPoint', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitInitDirection', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitInitPower', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitInitWavelength', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitInitPhi', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitInitTheta', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitRayIndex', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitFanIndex', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitTotalFanCount', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
        ('StoreHitTotalRaysInFan', False, 'Bool', 'Enable/disable additional data about light source '
              'and ray initial conditions to be stored with each ray hit.'),
      ])
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = SimulationSettingsProxy()
    if App.GuiUp:
      obj.ViewObject.Proxy = SimulationSettingsViewProxy(obj)

    # set active property to true again to trigger onChange handler
    obj.Active = True

    return obj

  def IsActive(self):
    return True

  def GetResources(self):
    return dict(Pixmap=find.iconpath('settings'),
                Accel='',
                MenuText='Inserts a simulation settings object into the project tree.',
                ToolTip='Inserts a simulation settings object into the project tree. Multiple '
                        'settings objects can coexist but only one can be active at a time.')

def loadSimulationSettings():
  Gui.addCommand('Insert settings', MakeSimulationSettings())
