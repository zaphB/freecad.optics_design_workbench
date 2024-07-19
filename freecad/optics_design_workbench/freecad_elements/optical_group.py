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
from .. import simulation



#####################################################################################################
class OpticalGroupProxy():
  '''
  Proxy of the point point source object responsible for the logic
  '''
  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''
    simulation.cancelSimulation()
    for _obj in find.lightSources():
      _obj.Proxy.redrawPreview(_obj)

  def setVisibleProperties(self, obj, props):
    dynamicProps = ['AbsorptionLength', 'RefractiveIndex', 'Reflectivity']
    for p in dynamicProps:
      obj.setEditorMode(p, 0 if p in props else 3)

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    simulation.cancelSimulation()

    if prop == 'OpticalType':
      oldType = getattr(self, 'oldType', None)
      newType = getattr(obj, prop)

      # set transparency to 0
      if oldType == 'Lens' and newType != 'Lens':
        for child in obj.ElementList:
          if hasattr(child.ViewObject, 'Transparency'):
            child.ViewObject.Transparency = 0
          pass

      # update which properties to display
      if newType == 'Mirror':
        self.setVisibleProperties(obj, ['Reflectivity'])
        obj.RecordHits = False

      elif newType == 'Lens':
        self.setVisibleProperties(obj, ['AbsorptionLength', 'RefractiveIndex'])
        for child in obj.ElementList:
          if hasattr(child.ViewObject, 'Transparency'):
            child.ViewObject.Transparency = 80
        obj.RecordHits = False

      elif newType == 'Absorber':
        self.setVisibleProperties(obj, [])
        obj.RecordHits = True

      elif newType == 'Vacuum':
        self.setVisibleProperties(obj, [])
        for child in obj.ElementList:
          if hasattr(child.ViewObject, 'Transparency'):
            child.ViewObject.Transparency = 80
        obj.RecordHits = True

      # update label
      if oldType and oldType in obj.Label:
        obj.Label = obj.Label.replace(oldType, newType)

      # update old type attribute of proxy
      self.oldType = newType

  def onRayHit(self, source, obj, point, power, isEntering, store):
    if store and obj.RecordHits:
      store.addRayHit(source=source, obj=obj, point=point, power=power, isEntering=isEntering)


#####################################################################################################
class OpticalGroupViewProxy():
  '''
  Proxy of the point point source object responsible for the view
  '''
  def __init__(self, obj):
    self.objectName = obj.Name

  def getIcon(self):
    '''Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown.'''
    return find.iconpath(App.activeDocument().getObject(self.objectName).OpticalType.lower())

  def attach(self, vobj):
    '''Setup the scene sub-graph of the view provider, this method is mandatory'''
    pass

  def updateData(self, obj, prop):
    '''If a property of the handled feature has changed we have the chance to handle this here'''
    pass

  def onDelete(self, obj, subelements):
    '''Here we can do something when the feature will be deleted'''
    return True

  def onChanged(self, obj, prop):
    '''Here we can do something when a single property got changed'''
    pass

  
#####################################################################################################
class MakeOpticalGroup:
  def __init__(self, opticalType):
    self.opticalType = opticalType

  def Activated(self):
    # create mirror object
    obj = App.activeDocument().addObject('App::LinkGroupPython', f'Optical{self.opticalType}Group')

    # create properties of object
    for section, entries in [
      ('OpticalProperties', [
        ('OpticalType', ['Mirror', 'Lens', 'Absorber', 'Vacuum'], 'Enumeration', 
              'Type of the optical element, can be reflective (=Mirror), refractive (=Lens), '
              'fully absorbing (=Absorber) or completely transparent (=Vacuum).'),
        ('RefractiveIndex', 2, 'Float', 
              'Refractive index of the material used for ray tracing.'),
        ('Reflectivity', 1, 'Float', 
              'Reflectivity coefficient used for ray tracing.'),
        ('AbsorptionLength', 0, 'Float', 
              'Not implemented')]),
      ('OpticalSimulationSettings', [
        ('RecordHits', False, 'Bool', 
              'Enable recording ray hits on this optical group to disk during simulations.'),
        ('HitCoordinateMode', ['global', 'local', 'relative to center-of-mass'], 'Enumeration', 
              'Not implemented'),
      ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = OpticalGroupProxy()
    obj.ViewObject.Proxy = OpticalGroupViewProxy(obj)

    # set OpticalType property again to trigger onChange handler
    obj.OpticalType = self.opticalType

    # add selection to group
    obj.ElementList = Gui.Selection.getSelection()

    return obj

  def IsActive(self):
    return bool(App.activeDocument())

  def GetResources(self):
    return dict(Pixmap=find.iconpath('add-'+self.opticalType.lower()),
                Accel='',
                MenuText='Make '+dict(
                            Mirror='mirrors',
                            Lens='lenses',
                            Absorber='absorbers',
                            Vacuum='detectors')[self.opticalType],
                ToolTip='Turn selected objects into optical '+dict(
                            Mirror='mirrors',
                            Lens='lenses',
                            Absorber='absorbers',
                            Vacuum='detectors')[self.opticalType],)

def loadGroups():
  Gui.addCommand('Make mirror', MakeOpticalGroup('Mirror'))
  Gui.addCommand('Make lens', MakeOpticalGroup('Lens'))
  Gui.addCommand('Make absorber', MakeOpticalGroup('Absorber'))
  Gui.addCommand('Make detector', MakeOpticalGroup('Vacuum'))
