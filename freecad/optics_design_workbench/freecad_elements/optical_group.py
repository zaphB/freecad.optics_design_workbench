__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

try:
  import FreeCADGui as Gui
  import FreeCAD as App
  from FreeCAD import Vector, Rotation
except ImportError:
  pass

from numpy import *

from . import common
from . import find
from .. import simulation
from .. import distributions

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
        ('ReflectedPowerDensity', 'DiracDelta(theta-theta_refl) * DiracDelta(phi-phi_refl)', 'String', 
              'Power density distribution function for reflected light. The direction of the '
              'resulting reflected ray '
              'is given by theta and phi. The angles of the incoming ray are given by theta_in and, '
              'phi_in, the angles of a ray reflected at an ideal mirror are given by theta_refl and '
              'phi_refl. The theta=0 direction corresponds to the local face normal. Defaults to '
              'ideal mirror behavior.'),
        ('RefractedPowerDensity', 
              # TODO: make this the default but needs performance improvement of random number generator:
              #       'DiracDelta(theta-theta_refr) * DiracDelta(phi-phi_refr)', 
              '', 'String', 
              'Power density distribution function for refracted light. The direction of the '
              'resulting refracted ray '
              'is given by theta and phi. The angles of the incoming ray are given by theta_in and, '
              'phi_in, the angles of a ray refracted at an ideal dielectric boundary according to '
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
                    'GratingDiffractionOrder', 'ReflectedPowerDensity', 'RefractedPowerDensity', 
                    'PowerThetaDomain', 'PowerPhiDomain', 'RayModificationProbabilityDensity', 
                    'ModifyThetaDomain', 'ModifyPhiDomain']
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

    # make sure domains are valid
    if prop in ('PowerThetaDomain', 'PowerPhiDomain', 'ModifyThetaDomain', 'ModifyPhiDomain'):
      raw = getattr(obj, prop)

      # select defaults and limits depending on property
      if 'Theta' in prop:
        default = '-pi,pi'
        limits = ['-pi', 'pi']
        spanLimits = [0, '2*pi']
      elif 'Phi' in prop:
        default = '-pi,pi'
        limits = ['-2*pi', '2*pi']
        spanLimits = [0, '4*pi']

      # parse range and replace value in case parsing changed it
      parsed, (l1,l2) = self._parsedDomain(raw, default=default, 
                                           limits=limits, 
                                           spanLimits=spanLimits)
      if raw != parsed:
        setattr(obj, prop, parsed)

  def onInitializeSimulation(self, obj, state, ident):
    # clear cached random number generators on start and exit of simulation
    self._clearVrv(obj)

  def onExitSimulation(self, obj, ident):
    # clear cached random number generators on start and exit of simulation
    self._clearVrv(obj)

  def onRayHit(self, source, obj, point, direction, power, isEntering, metadata, store):
    if store and obj.RecordHits:
      store.addRayHit(source=source, obj=obj, point=point, direction=direction, 
                      power=power, isEntering=isEntering, metadata=metadata)


  def _getVrv(self, obj, kind):
    '''
    return (cached) random variables for stochastic ray postprocessing (or False if 
    probability density is empty)
    '''
    if NON_SERIALIZABLE_STORE.get(self, None) is None:
      NON_SERIALIZABLE_STORE[self] = {}
    
    if NON_SERIALIZABLE_STORE[self].get('vrv'+kind, None) is None:
      # module global variable and not to self, because attributes of self should be serializable
      if kind == 'reflect':
        if obj.ReflectedPowerDensity:
          NON_SERIALIZABLE_STORE[self]['vrv'+kind] = (
              distributions.VectorRandomVariable(
                    probabilityDensity='('+obj.ReflectedPowerDensity+')*abs(sin(theta))', # add correction for spherical coordinate area element size
                    variableOrder=('theta', 'phi'),
                    variableDomains=dict(
                      theta=obj.Proxy._parsedDomain(obj.PowerThetaDomain)[1], 
                      phi=obj.Proxy._parsedDomain(obj.PowerPhiDomain)[1]
                    ),
              )
          )
        else:
          NON_SERIALIZABLE_STORE[self]['vrv'+kind] = False
      if kind == 'refract':
        if obj.RefractedPowerDensity:
          NON_SERIALIZABLE_STORE[self]['vrv'+kind] = (
              distributions.VectorRandomVariable(
                    probabilityDensity='('+obj.RefractedPowerDensity+')*abs(sin(theta))', # add correction for spherical coordinate area element size
                    variableOrder=('theta', 'phi'),
                    variableDomains=dict(
                      theta=obj.Proxy._parsedDomain(obj.PowerThetaDomain)[1], 
                      phi=obj.Proxy._parsedDomain(obj.PowerPhiDomain)[1]
                    ),
              )
          )
        else:
          NON_SERIALIZABLE_STORE[self]['vrv'+kind] = False
      if kind == 'modify':
        if obj.RayModificationProbabilityDensity:
          NON_SERIALIZABLE_STORE[self]['vrv'+kind] = (
              distributions.VectorRandomVariable(
                    probabilityDensity=obj.RayModificationProbabilityDensity,
                    variableOrder=('theta', 'phi'),
                    variableDomains=dict(
                      theta=obj.Proxy._parsedDomain(obj.ModifyThetaDomain)[1], 
                      phi=obj.Proxy._parsedDomain(obj.ModifyPhiDomain)[1]
                    ),
              )
          )
        else:
          NON_SERIALIZABLE_STORE[self]['vrv'+kind] = False
    return NON_SERIALIZABLE_STORE[self]['vrv'+kind]


  def _clearVrv(self, obj):
    for kind in 'reflect refract modify'.split():
      _stored = NON_SERIALIZABLE_STORE.get(self, {})
      _stored['vrv'+kind] = None
      NON_SERIALIZABLE_STORE[self] = _stored


  def applyStochasticRayCorrections(self, obj, directionIn, idealDirectionOut, normal):
    '''
    Calculate direction of outgoing ray according to stochastic properties of the optical
    object, i.e. ReflectedPowerDensity, RefractedPowerDensity and RayModificationProbabilityDensity
    Takes the ideal (Snell's law for lenses, or specular reflection for mirrors) outgoing direction,
    the incoming direction and the face normal (pointing into the body) as input parameters.
    '''
    # prepare vectors needed to calculate direction of reflected ray
    _arccos = lambda x: arccos(max([-1, min([1, x])]))
    thetaIn = _arccos( directionIn * normal/normal.Length )
    phiIn = 0
    thetaRefl = _arccos( idealDirectionOut/idealDirectionOut.Length * normal/normal.Length )
    phiRefl = 0

    # set ideal direction as default
    directionOut = idealDirectionOut

    # determine outgoing direction using mirrors reflected power density
    #print(obj.ReflectedPowerDensity, obj.Proxy._parsedDomain(obj.PowerThetaDomain)[1], obj.Proxy._parsedDomain(obj.PowerPhiDomain)[1])
    if obj.OpticalType == 'Mirror':
      kind = 'reflect' 
    elif obj.OpticalType == 'Lens':
      kind = 'refract'
    else:
      raise ValueError(f'applyStochasticRayCorrections can only be called on mirrors and lenses optical types, found {obj.OpticalType=}')
    vrv = self._getVrv(obj, kind=kind)
    if vrv:
      vrv.compile( theta_in=thetaIn, phi_in=phiIn, theta_refl=thetaRefl, phi_refl=phiRefl )
      thetaOut, phiOut = vrv.draw()
      #print(thetaOut, phiOut)
      directionOut = (Rotation(normal, phiOut/pi*180) 
                        * Rotation(normal.cross(directionIn), thetaOut/pi*180) 
                        * normal)

    # modify outgoing direction using modify probability density
    #print(obj.RayModificationProbabilityDensity, obj.Proxy._parsedDomain(obj.ModifyThetaDomain)[1], obj.Proxy._parsedDomain(obj.ModifyPhiDomain)[1])
    vrv = self._getVrv(obj, kind='modify')
    if vrv:
      thetaModify, phiModify = vrv.draw()
      #print(thetaModify, phiModify)
      directionOut = (Rotation(directionOut, phiModify/pi*180) 
                            * Rotation(directionOut.cross(directionIn), thetaModify/pi*180) 
                            * directionOut)
    
    return directionOut


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
