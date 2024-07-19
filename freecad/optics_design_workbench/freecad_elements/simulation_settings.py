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
    simulation.cancelSimulation()

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
      simulation.cancelSimulation()
      for settings in find.simulationSettings():
        if settings != obj:
          settings.Active = False
    
    # if any other property changed just cancel if it was on the active settings object 
    if obj.Active:
      simulation.cancelSimulation()

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
          val = int(val)
        except ValueError:
          setattr(obj, prop, 'inf')
        else:
          # limit to positive numbers
          if val < 0:
            setattr(obj, prop, '1')


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
        ('SimulationDataFolder', '{projectName}.opticalSimulationResults', 'Path', 
              'Path to folder to store simulation results in. The following placeholders '
              'are possible: {projectName} will be replaced with FCStd filename of the project, '
              '{settingsName} will be replaced with the Label property of this settings object '
              'and %d %m and %Y and similar will be replaced according to Python\'s '
              'time.strftime'),
        ('EnableStoreSingleShotData', False, 'Bool', 'Store rays and hits to disk for every single-shot '
              'simulation.'),
      ]),
      ('OpticalSimulationPerformanceSettings', [
        ('EndAfterIterations', 'inf', 'String', 'Number of iterations after which simulation should stop'),
        ('EndAfterRays', 'inf', 'String', 'Number of traced rays after which simulation should stop'),
        ('EndAfterHits', 'inf', 'String', 'Number of recorded hits after which simulation should stop'),
        ('RaysPerIteration', 100, 'Float', 'Number of rays to place per simulation iteration for random '
              'and pseudo random modes.'),
        ('MaxIntersections', 100, 'Float', 'Maximum number of intersections (reflections/refractions/'
              'detections) that a ray may have with optical objects.'),
        ('MaxRayLength', 100, 'Float', 'Maximum length of each ray segment, i.e. the total ray length '
              'may be up to MaxIntersections*MaxRayLength. This is not a strict '
              'limit but rather a possibility for the ray tracer to save time by ignoring '
              'objects that are farther away from a given ray origin than this limit. Longer ray '
              'segments may still occur.'),
        ('ShowRaysInContinuousMode', True, 'Bool', 'Allows to switch of displaying rays in '
              'continuous simulation modes to speed up the calculation.'),
        ('WorkerProcessCount', 'num_cpus', 'String', 'Number of worker processes to spawn for continuous '
              f'simulation modes. Should be an integer or "num_cpus" ( = {simulation.cpuCount()} ).'),
      ]),
      ('OpticalSimulationPreviewSettings', [
        ('MaxIntersectionsPreviewRays', 10, 'Float', 'Limit maximum intersections for preview rays. '
             'Preview rays are the rays automatically placed while editing the geometry. These limits '
             'do not apply when using the "Recalculate fans" command.'),
        ('MaxFanCountPreviewRays', 2, 'Float', 'Limit maximum fan count for preview rays.'
             'Preview rays are the rays automatically placed while editing the geometry. These limits '
             'do not apply when using the "Recalculate fans" command.'),
        ('MaxRaysPerFanPreviewRays', 10, 'Float', 'Limit maximum number of rays per fan for preview.'
             'Preview rays are the rays automatically placed while editing the geometry. These limits '
             'do not apply when using the "Recalculate fans" command.'),
      ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = SimulationSettingsProxy()
    obj.ViewObject.Proxy = SimulationSettingsViewProxy(obj)

    # set active property to true again to trigger onChange handler
    obj.Active = True

    return obj

  def IsActive(self):
    return bool(App.activeDocument())

  def GetResources(self):
    return dict(Pixmap=find.iconpath('settings'),
                Accel='',
                MenuText='Inserts a simulation settings object into the project tree.',
                ToolTip='Inserts a simulation settings object into the project tree. Multiple '
                        'settings objects can coexist but only one can be active at a time.')

def loadSimulationSettings():
  Gui.addCommand('Insert settings', MakeSimulationSettings())
