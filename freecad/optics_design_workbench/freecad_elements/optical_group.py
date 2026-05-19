__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

try:
  import FreeCADGui as Gui
  import FreeCAD as App
except ImportError:
  pass

from . import common
from . import find
from .. import simulation

# global dict with keys being PointSourceProxy objects and values being 
# more dicts that store pseudo-attributes. This awkward attribute storing
# format allows to bypass the serializer which wants to safe the Proxy
# objects whenever the FreeCAD project is saved.
NON_SERIALIZABLE_STORE = {}

#####################################################################################################
class OpticalGroupProxy(common.GenericFreecadElementProxy):
  
  def _properties(self):
    return [
      ('OpticalProperties', [
        ('OpticalType', ['Mirror', 'Lens', 'Grating', 'Absorber', 'Vacuum'], 'Enumeration', 
              'Type of the optical element, can be reflective (=Mirror), refractive (=Lens), '
              'grating (=Grating), '
              'fully absorbing (=Absorber) or completely transparent (=Vacuum).'),
        ('RefractiveIndex', 2, 'Float', 
              'Refractive index of the material used for ray tracing.'),
        ('ReflectedPowerDensity', 'DiracDelta(theta-theta_refl) + DiracDelta(phi-phi_refl)', 'String', 
              'Power density distribution function for reflected light. The direction of the '
              'resulting reflected ray '
              'is given by theta and phi. The angles of the incoming ray are given by theta_in and, '
              'phi_in, the angles of a ray reflected at an ideal mirror are given by theta_refl and '
              'phi_refl. The theta=0 direction corresponds to the local face normal. Defaults to '
              'ideal mirror behavior.'),
        ('RefractedPowerDensity', 'DiracDelta(theta-theta_refr) + DiracDelta(phi-phi_refr)', 'String', 
              'Power density distribution function for refracted light. The direction of the '
              'resulting refracted ray '
              'is given by theta and phi. The angles of the incoming ray are given by theta_in and, '
              'phi_in, the angles of a ray reflected at an ideal dielectric boundary according to '
              'Snell\'s law are given by theta_refr and '
              'phi_refr. The theta=0 direction corresponds to the local face normal. '
              'Defaults to ideal dielectric behavior.'),
        ('PowerThetaDomain', '-pi/2, pi/2', 'String', 'Min and max value for polar angle theta to consider '
              'when generating angles of the Reflected/Refracted Power Density.'),
        ('PowerPhiDomain', '0, 2*pi', 'String', 'Min and max value for azimuthal angle phi to consider '
              'when generating angles of the Reflected/Refracted Power Density.'),
        ('RayModificationProbabilityDensity', 'DiracDelta(theta)', 'String', 
              'Modifies outgoing rays by the given probability density function. Available '
              'variables are theta and phi. Theta and phi rotate the resulting ray, with '
              'theta=0 (and phi arbitrary) implying no rotation at all. The phi=0 angle '
              'is the direction of smallest angle between reflecting/refracting surface '
              'and the outgoing ray before modification. Defaults to no modification at all.'),
        ('ModifyThetaDomain', '-pi/2, pi/2', 'String', 'Min and max value for polar angle theta to consider '
              'when generating modification angles for outgoing rays according to Ray Modification '
              'Probability Density.'),
        ('ModifyPhiDomain', '0, 2*pi', 'String', 'Min and max value for azimuthal angle phi to consider '
              'when generating modification angles for outgoing rays according to Ray Modification '
              'Probability Density.'),
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
    ]

  def setVisibleProperties(self, obj, props):
    dynamicProps = ['AbsorptionLength', 'RefractiveIndex', 'Reflectivity', 'GratingType', 
                    'GratingLinesPerMillimeter', 'GratingLinesOrientation', 
                    'GratingDiffractionOrder']
    for p in dynamicProps:
      obj.setEditorMode(p, 0 if p in props else 3)

  def onChanged(self, obj, prop):
    '''Do something when a property has changed'''
    self._ensurePropertiesExist(obj)

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
        self.setVisibleProperties(obj, ['Reflectivity', 'ReflectedPowerDensity', 'PowerThetaDomain', 
                                        'PowerPhiDomain', 'RayModificationProbabilityDensity', 
                                        'ModifyThetaDomain', 'ModifyPhiDomain'])
        obj.RecordHits = False

      elif newType == 'Lens':
        self.setVisibleProperties(obj, ['AbsorptionLength', 'RefractiveIndex', 'RefractedPowerDensity', 
                                        'PowerThetaDomain', 'PowerPhiDomain', 'RayModificationProbabilityDensity',
                                        'ModifyThetaDomain', 'ModifyPhiDomain'])
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
class OpticalGroupViewProxy(common.GenericFreecadElementViewProxy):

  def _properties(self):
    return [
      ('ColorizeRays', [
        ('Weight', 0, 'Float', 
              'Weight of ray colorization, should be between 0 and 1. 1 means set color '
              'immediately, 0 means do not change color at all.'),
        ('Color', (0.,0.,0.,0.), 'Color', 
              'Color to mix with previous ray color during colorization. Weight determines '
              'fraction of old and new colors in mix.'),
      ]),
    ]

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
class MakeOpticalGroup(common.GenericMakeFreecadElement):
  def __init__(self, opticalType):
    self.opticalType = opticalType
    super().__init__(OpticalGroupProxy, OpticalGroupViewProxy, f'Optical{self.opticalType}Group')


  def Activated(self):
    obj = super().Activated() 
    
    # set OpticalType property again to trigger onChange handler
    obj.OpticalType = self.opticalType

    # add selection to group
    obj.ElementList = Gui.Selection.getSelection()

    return obj
  

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
