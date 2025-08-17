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
import scipy.optimize
import sympy as sy

from .generic_source import *
from .common import *
from . import ray
from . import find
from .. import simulation
from .. import distributions
from .. import io

#####################################################################################################
class SurfaceSourceProxy(GenericSourceProxy):

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    pass


  def _generateRays(self, obj, mode, maxFanCount=inf, maxRaysPerFan=inf, **kwargs):
    '''
    This generator yields each ray to be traced for one simulation iteration.
    '''
    pass


#####################################################################################################
class SurfaceSourceViewProxy(GenericSourceViewProxy):
  pass

  
#####################################################################################################
class AddSurfaceSource(AddGenericSource):

  def Activated(self):
    # create new feature python object
    obj = App.activeDocument().addObject('App::LinkGroupPython', 'OpticalSurfaceSource')

    # create properties of object
    for section, entries in [
      ('OpticalEmission', [
        ('ActiveSurfaces', [], 'LinkSubList', 'List of surfaces if child elements that '
                  'we want to emit rays from. Empty list implies that all faces emit.'),
        ('LocalPowerDensity', 'cos(theta)', 'String',  
                  'Emitted optical power per solid angle at each surface element. '
                  'The expression may contain any mathematical '
                  'function contained in the numpy module and the polar angle "theta" '
                  'to make the emission of each surface element depend on the emission angle.'
                  'All rays placed by this light source begin on the selected surfaces.'),
        ('Wavelength', 500, 'Float', 'Wavelength of the emitted light in nm.'),
      ]),
      ('OpticalSimulationSettings', [
        *self.defaultSimulationSettings(obj),
        ('ThetaRandomNumberGeneratorMode', '?', 'String', ''),
        ('ThetaResolutionNumericMode', '1e6', 'String', ''),
        ('TotalFansRays', 100, 'Integer', 'Number of rays to place in fan mode.'),
       ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = SurfaceSourceProxy()
    if App.GuiUp:
      obj.ViewObject.Proxy = SurfaceSourceViewProxy()

    # make mode readonly
    obj.setEditorMode('ThetaRandomNumberGeneratorMode', 1)

    # add selection to group
    obj.ElementList = Gui.Selection.getSelection()

    return obj

  def IsActive(self):
    return True

  def GetResources(self):
    return dict(Pixmap=self.iconpath(),
                Accel='',
                MenuText='Make point source',
                ToolTip='Add a point light source to the current project.')

def loadSurfaceSource():
  Gui.addCommand('Add surface source', AddSurfaceSource())
