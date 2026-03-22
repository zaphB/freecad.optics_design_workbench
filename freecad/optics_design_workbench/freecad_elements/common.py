__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

import time

from .. import simulation

_LAST_PROCESS_EVENTS_CALL = time.time()
_MIN_UPDATE_INTERVAL = 1e-2

class SimulationEnded(RuntimeError):
  pass

def keepGuiResponsive(raiseIfSimulationDone=False):
  from ..detect_pyside import QApplication  
  global _LAST_PROCESS_EVENTS_CALL
  if time.time()-_LAST_PROCESS_EVENTS_CALL > _MIN_UPDATE_INTERVAL:
    _LAST_PROCESS_EVENTS_CALL = time.time()

    if QApplication.instance():
      # process Qt events
      QApplication.processEvents()
      Gui.updateGui()
      QApplication.processEvents()

    # check whether simulation was canceled and raise SimulationEnded if so
    if raiseIfSimulationDone and (simulation.isCanceled() or simulation.isFinished()):
      raise SimulationEnded()
      
def keepGuiResponsiveAndRaiseIfSimulationDone():
  keepGuiResponsive(raiseIfSimulationDone=True)


class GenericFreecadElementProxy:
  def _properties(self):
    return []

  def _ensurePropertiesExist(self, obj):
    # create properties of object
    for section, entries in self._properties():
      for name, default, kind, tooltip in entries:
        if not hasattr(obj, name):
          obj.addProperty('App::Property'+kind, name, section, tooltip)
          setattr(obj, name, default)

  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''
    self._ensurePropertiesExist(obj)

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    self._ensurePropertiesExist(obj)


class GenericFreecadElementViewProxy:
  def _properties(self):
    return []

  def _ensurePropertiesExist(self, obj):
    # create view object properties
    for section, entries in self._properties():
      for name, default, kind, tooltip in entries:
        if not hasattr(obj.ViewObject, name):
          obj.ViewObject.addProperty('App::Property'+kind, name, section, tooltip)
          setattr(obj.ViewObject, name, default)

  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''
    self._ensurePropertiesExist(obj)

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    self._ensurePropertiesExist(obj)


class GenericMakeFreecadElement:
  def __init__(self, proxyClass, viewProxyClass, 
               objectName, objectKind='App::LinkGroupPython'):
    self._proxyClass = proxyClass
    self._viewProxyClass = viewProxyClass
    self._objectName = objectName
    self._objectKind = objectKind

  def Activated(self):
    # create mirror object
    obj = App.activeDocument().addObject(self._objectKind, self._objectName)

    # register custom proxy and view provider proxy and ensure all properties exist
    obj.Proxy = self._proxyClass()
    obj.Proxy._ensurePropertiesExist(obj)
    if App.GuiUp:
      obj.ViewObject.Proxy = self._viewProxyClass(obj)
      obj.ViewObject.Proxy._ensurePropertiesExist(obj)

    # return created object
    return obj

  def IsActive(self):
    return True
