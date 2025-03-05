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

# global dict with keys being PointSourceProxy objects and values being 
# more dicts that store pseudo-attributes. This awkward attribute storing
# format allows to bypass the serializer which wants to safe the Proxy
# objects whenever the FreeCAD project is saved.
NON_SERIALIZABLE_STORE = {}

#####################################################################################################
class OpticalGroupProxy():
  def execute(self, obj):
    '''Do something when doing a recomputation, this method is mandatory'''

  def setVisibleProperties(self, obj, props):
    dynamicProps = ['AbsorptionLength', 'RefractiveIndex', 'Reflectivity', 'GratingType', 
                    'GratingLinesPerMillimeter', 'GratingLinesOrientation', 
                    'GratingDiffractionOrder']
    for p in dynamicProps:
      obj.setEditorMode(p, 0 if p in props else 3)

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''

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

      elif newType == 'Grating':
        self.setVisibleProperties(obj, ['AbsorptionLength', 'RefractiveIndex',
                                  'GratingType', 'GratingLinesPerMillimeter', 
                                  'GratingLinesOrientation', 'GratingDiffractionOrder'])
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
    
    if prop == 'AbsorptionLength':
      val = getattr(obj, prop)
      try:
        val = float(val)
      except ValueError:
        setattr(obj, prop, 'inf')

  def onInitializeSimulation(self, obj, state, ident):
    pass

  def onExitSimulation(self, obj, ident):
    pass

  def onRayHit(self, source, obj, point, direction, power, isEntering, metadata, store):
    if store and obj.RecordHits:
      store.addRayHit(source=source, obj=obj, point=point, direction=direction, 
                      power=power, isEntering=isEntering, metadata=metadata)


#####################################################################################################
class OpticalGroupViewProxy():

  def getIcon(self):
    '''Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown.'''
    return find.iconpath(NON_SERIALIZABLE_STORE[self].OpticalType.lower())

  def attach(self, vobj):
    NON_SERIALIZABLE_STORE[self] = vobj.Object
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
        ('OpticalType', ['Mirror', 'Lens', 'Grating', 'Absorber', 'Vacuum'], 'Enumeration', 
              'Type of the optical element, can be reflective (=Mirror), refractive (=Lens), '
              'grating (=Grating), '
              'fully absorbing (=Absorber) or completely transparent (=Vacuum).'),
        ('RefractiveIndex', 2, 'Float', 
              'Refractive index of the material used for ray tracing.'),
        ('Reflectivity', 1, 'Float', 
              'Reflectivity coefficient used for ray tracing.'),
        ('AbsorptionLength', 'inf', 'String', 
              'Optical absorption length in the material in 1/mm'),
        ('GratingType', ['Reflection', 'Transmission'], 'Enumeration', 
              'Select whether grating should be reflective of transmissive.'),
        ('GratingLinesPerMillimeter', 1000, 'Float', 
              'Number of grating lines per millimeter.'),
        ('GratingLinesOrientation', (0,0,1), 'Vector',
              'Normal of a hypothetical set of planes that intersect the grating surface, to define '
              'the rulings of the grating as these intersection lines'),
        ('GratingDiffractionOrder', 1, 'Integer', 
              'Order of diffraction at which to place refracted/transmitted rays.'),
      ]),
      ('OpticalSimulationSettings', [
        ('RecordHits', False, 'Bool', 
              'Enable recording ray hits on this optical group to disk during simulations.'),
      ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj, name, default)

    # create custom view object properties
    for section, entries in [
      ('ColorizeRays', [
        ('Weight', 0, 'Float', 
              'Weight of ray colorization, should be between 0 and 1. 1 means set color '
              'immediately, 0 means do not change color at all.'),
        ('Color', (0.,0.,0.,0.), 'Color', 
              'Color to mix with previous ray color during colorization. Weight determines '
              'fraction of old and new colors in mix.'),
      ]),
    ]:
      for name, default, kind, tooltip in entries:
        obj.ViewObject.addProperty('App::Property'+kind, name, section, tooltip)
        setattr(obj.ViewObject, name, default)

    # register custom proxy and view provider proxy
    obj.Proxy = OpticalGroupProxy()
    if App.GuiUp:
      obj.ViewObject.Proxy = OpticalGroupViewProxy()

    # set OpticalType property again to trigger onChange handler
    obj.OpticalType = self.opticalType

    # add selection to group
    obj.ElementList = Gui.Selection.getSelection()

    return obj

  def IsActive(self):
    return True

  def GetResources(self):
    return dict(Pixmap=find.iconpath('add-'+self.opticalType.lower()),
                Accel='',
                MenuText='Make '+dict(
                            Mirror='mirrors',
                            Lens='lenses',
                            Grating='gratings',
                            Absorber='absorbers',
                            Vacuum='detectors')[self.opticalType],
                ToolTip='Turn selected objects into optical '+dict(
                            Mirror='mirrors',
                            Lens='lenses',
                            Grating='gratings',
                            Absorber='absorbers',
                            Vacuum='detectors')[self.opticalType],)

def loadGroups():
  Gui.addCommand('Make mirror', MakeOpticalGroup('Mirror'))
  Gui.addCommand('Make lens', MakeOpticalGroup('Lens'))
  Gui.addCommand('Make grating', MakeOpticalGroup('Grating'))
  Gui.addCommand('Make absorber', MakeOpticalGroup('Absorber'))
  Gui.addCommand('Make detector', MakeOpticalGroup('Vacuum'))
