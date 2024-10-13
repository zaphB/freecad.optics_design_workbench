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
from .. import simulation
from . common import *


class OpticalSimulationAction:
  def __init__(self, action):
    self.action = action

  def Activated(self):
    # call clear method of all light source Proxies to erase all visible rays
    if self.action == 'clear':
      for obj in find.lightSources():
        obj.Proxy.clear(obj)
        
        # make sure GUI does not freeze during this
        keepGuiResponsive()
    else:
      # forward action to simulations submodule
      simulation.runAction(self.action)

  def IsActive(self):
    return True

  def GetResources(self):
    return dict(
      Pixmap=find.iconpath(self.action),
      Accel='',
      **(dict(
        clear=dict(
          MenuText='Clear rays',
          ToolTip='Clear all displayed rays from the project.'
        ),
        fans=dict(
          MenuText='Recalculate fans',
          ToolTip='Calculate and display ray fans for all light sources.'
        ),
        singlepseudo=dict(
          MenuText='Run a single pseudo-random iteration',
          ToolTip='Run and display a single pseudo-random Monte-Carlo iteration.'
        ),
        singletrue=dict(
          MenuText='Run a single true random iteration',
          ToolTip='Run and display a single true random Monte-Carlo iteration.'
        ),
        pseudo=dict(
          MenuText='Start pseudo-random simulation',
          ToolTip='Start running the pseudo-random Monte-Carlo simulation in '
                  'the background.'
        ),
        true=dict(
          MenuText='Start true random simulation',
          ToolTip='Start running the true random Monte-Carlo simulation in '
                  'the background.'
        ),
        stop=dict(
          MenuText='Stop running simulation',
          ToolTip='Stop the simulation currently running in the background.'
        )
      )[self.action]))

def loadSimulationActions():
  Gui.addCommand('Clear all rays', OpticalSimulationAction('clear'))
  Gui.addCommand('Place ray fans', OpticalSimulationAction('fans'))
  Gui.addCommand('Single pseudo random', OpticalSimulationAction('singlepseudo'))
  Gui.addCommand('Single true random', OpticalSimulationAction('singletrue'))
  Gui.addCommand('Continuous pseudo random', OpticalSimulationAction('pseudo'))
  Gui.addCommand('Continuous true random', OpticalSimulationAction('true'))
  Gui.addCommand('Stop continuous', OpticalSimulationAction('stop'))
