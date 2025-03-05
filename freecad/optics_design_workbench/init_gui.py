__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


import FreeCADGui as Gui
import FreeCAD as App

from . import freecad_elements

class OpticsDesignWorkbench(Gui.Workbench):
  MenuText = 'Optics Design'
  ToolTip = 'Ray tracing Monte-Carlo simulation for optics design and optimization'
  Icon = freecad_elements.find.iconpath('workbench')
  toolbox = []

  def Initialize(self):
      '''This function is executed when FreeCAD starts'''
      # import here all the needed files that create your FreeCAD commands
      self.toolbox = [
        # sources
        'Add point source', 
        'Add replay source', 

        # optical elements
        'Make mirror', 
        'Make lens', 
        'Make grating', 

        # detectors
        'Make absorber', 
        'Make detector', 

        # place settings node
        'Insert settings',

        # place/start/stop simulation in the various modes
        'Clear all rays',
        'Place ray fans',
        'Single pseudo random',
        'Single true random',
        'Continuous pseudo random',
        'Continuous true random',
        'Stop continuous',
      ]
      
      self.appendToolbar(self.__class__.MenuText, self.toolbox)
      self.appendMenu(self.__class__.MenuText, self.toolbox)

  def Activated(self):
      '''This function is executed when the workbench is activated'''
      return

  def Deactivated(self):
      '''This function is executed when the workbench is deactivated'''
      return

  def ContextMenu(self, recipient):
      '''This is executed whenever the user right-clicks on screen'''
      self.appendContextMenu(self.__class__.MenuText, self.toolbox)

  def GetClassName(self):
      # this function is mandatory if this is a full python workbench
      return 'Gui::PythonWorkbench'

Gui.addWorkbench(OpticsDesignWorkbench())
freecad_elements.loadAll()
