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
import time

from . import find
from ..simulation.tracing_cache import *
from .common import *


class Ray():
  '''
  Class representing an individual ray.
  '''
  def __init__(self, lightSource, initPoint, initDirection, 
               initPower=1, wavelength=1, metadata={}):
    self.lightSource = lightSource
    self.initPoint = initPoint
    self.initDirection = initDirection
    self.initPower = initPower
    self.initWavelength = wavelength
    self.metadata = metadata
  
     
  def traceRay(self, powerTol=1e-6, maxRayLength=None,
               maxIntersections=None, store=False,
               metadata={}):
    '''
    Find all reflection/refraction/detection points of this ray. Returns a
    generator that yields (p1,p2), power, medium tuples. p1, p2 are two
    vectors describing a ray segment. power is the ray power at p1. medium
    is None for vacuum or the FreeCAD object if the ray is traveling through
    and optical object.
    '''
    if _sett := find.activeSimulationSettings():
      # calc ray length and intersection limits from settings
      if maxRayLength is None:
        maxRayLength = ( self.lightSource.MaxRayLengthScale 
                          * _sett.MaxRayLength )
      if maxIntersections is None:
        maxIntersections = (self.lightSource.MaxIntersectionsScale
                              *_sett.MaxIntersections )

      # construct ray metadata dictionary according to selected properties
      # in simulation settings
      _enabledKeys = [k.lower()[8:] for k in _sett.__dict__.keys() 
                          if k.startswith('StoreHit') and getattr(_sett, k)]
      rayMetadata = dict(self.metadata)
      rayMetadata.update(metadata)
      rayMetadata.update(self.__dict__)
      #print('full metadata:', rayMetadata)
      #print('enabled keys:', _enabledKeys)
      rayMetadata = {k:v for k,v in rayMetadata.items() 
                                    if k.lower() in _enabledKeys }
      #print('filtered metadata:', rayMetadata)

    else:
      # setup defaults if no settings object exists
      if maxRayLength is None:
        maxRayLength = 100 * self.lightSource.MaxRayLengthScale
      if maxIntersections is None:
        maxIntersections = 10 * self.lightSource.MaxIntersectionsScale
      
      # default to empty metadata
      rayMetadata = {}

    # counters for total ray intersections and index of active optical 
    # element in sequential mode
    sequenceIndex = 0
    numIntersections = 0

    # variables to store current state during intersection finder loop
    prevPoint, currentPoint = self.initPoint, self.initPoint
    currentDirection = self.initDirection
    prevMedium, currentMedium = None, None
    prevPower, currentPower = self.initPower, self.initPower
    colorChange = None

    # trace loop
    while True:
      # this loop may run for quite some time, keep GUI responsive by handling events
      keepGuiResponsiveAndRaiseIfSimulationDone()
      
      # stop tracing if maxIntersections limit is reached
      if numIntersections >= maxIntersections:
        break
      numIntersections += 1

      # find next intersection
      intersect = self.findNearestIntersection(currentPoint, currentDirection, 
                                               maxRayLength=maxRayLength, 
                                               sequenceIndex=sequenceIndex)
      if intersect is None:
        # if no intersection is found yield segment with maxLength and exit loop
        yield ((currentPoint, currentPoint + currentDirection/currentDirection.Length*maxRayLength), 
                currentPower, currentMedium, colorChange)
        break
      obj, face, point = intersect

      # update current state
      prevPoint, prevPower, prevMedium = currentPoint, currentPower, currentMedium
      currentPoint = point

      # add yield latest segment
      yield (prevPoint, currentPoint), prevPower, prevMedium, colorChange

      # calculate normal and whether ray is facing the object from the outside or the inside
      normal, isEntering = self.getNormal(face, prevPoint, currentPoint)

      # run onHit handler of object that caused intersection
      obj.Proxy.onRayHit(source=self.lightSource, obj=obj, 
                         point=currentPoint, direction=currentDirection, 
                         power=currentPower, isEntering=isEntering, 
                         metadata=rayMetadata, store=store)

      # set colorChange to value requested by the hit object
      if obj.ViewObject is not None and obj.ViewObject.Weight != 0:
        colorChange = (obj.ViewObject.Weight, obj.ViewObject.Color)
      else:
        colorChange = None

      # hit mirror: direction is mirrored at normal, 
      # medium is unchanged, power is altered according to reflectivity
      if obj.OpticalType == 'Mirror':
        currentDirection = self.mirror(currentDirection, normal)
        currentPower *= obj.Reflectivity

        # mirrors have exactly one reflection in sequential mode
        sequenceIndex += 1
           
      # hit lens: direction is altered according to Snells law,
      # medium is changed depending on whether left or entered the lens
      elif obj.OpticalType == 'Lens':
        # ray enters lens
        if isEntering:
          if currentMedium is not None:
            raise ValueError('ray entered lens while already being inside a lens, '
                             'get rid of any overlapping lenses in your project')
          n1 = 1
          currentMedium = obj
          n2 = currentMedium.RefractiveIndex

        # ray exits lens (or may suffer total reflection)
        else:
          if currentMedium is None:
            raise ValueError('ray exited lens without having entered before, '
                             'get rid of any overlapping lenses in your project')
          n1 = currentMedium.RefractiveIndex
          n2 = 1

        # update ray direction according to Snell's law
        currentDirection, isTotalReflection = self.snellsLaw(
                                      currentDirection/currentDirection.Length,
                                      n1, n2, normal)

        # if ray traveled in exit direction and not total reflection occurred,
        # set current medium to vacuum
        if not isEntering and not isTotalReflection:
          currentMedium = None

          # increment sequence index only after ray left lens 
          # (without internal reflection)
          sequenceIndex += 1

      # hit absorber: intensity is changed / ray is ended if intensity below min
      elif obj.OpticalType == 'Absorber':
        currentPower = 0
        sequenceIndex += 1

      # hit vacuum: do nothing at all to direction / intensity
      elif obj.OpticalType == 'Vacuum':
        sequenceIndex += 1
            
      # end if beam died
      if currentPower < powerTol:
        break
  
  def _getDistTol(self, distTol):
    if distTol is None:
      distTol = 1e-2
      if settings := find.activeSimulationSettings():
        distTol = float(settings.DistanceTolerance)
    return max([distTol, 1e-6])

  def findNearestIntersection(self, start, direction, maxRayLength, distTol=None, sequenceIndex=None):
    '''
    Find the closest relevant optical object intersecting with the ray
    of given start and direction. Start and direction are expected to be
    given in global coordinates.
    '''
    distTol = self._getDistTol(distTol)

    line = Part.makeLine(start, start+direction/direction.Length*maxRayLength)
    intersects = []
    
    # loop through all relevant optical groups
    for group in find.relevantOpticalObjects(self.lightSource, sequenceIndex=sequenceIndex):

      # this loop may run for quite some time, keep GUI responsive by handling events
      keepGuiResponsiveAndRaiseIfSimulationDone()

      # only care if bounding box is closer to start point than maxRayLength and 
      # if bounding box actually intersects with the ray
      if hasattr(group, 'Shape'):
        sbb = cachedBoundBox(cachedShape(group))
        #sbb.enlarge(distTol) => for some strange reason this causes off-centered profiles in gaussian-test, keep disabled for now...
        if ( ( not isfinite(maxRayLength)
                or any([(sbb.getPoint(i)-start).Length
                                  < maxRayLength 
                                        for i in range(8)]) )
            and sbb.intersect(start, direction) ):

          # loop through all faces
          for face in cachedFaces(cachedShape(group)):

            # this loop may run for quite some time, keep GUI responsive by handling events
            keepGuiResponsiveAndRaiseIfSimulationDone()

            # only care if bounding box of face intersects with ray
            fbb = cachedBoundBox(face)
            fbb.enlarge(distTol)
            if fbb.intersect(start, direction):

              # find intersection points and loop through all of them
              if intersect := line.Curve.intersect(face.Surface):
                points, _ = intersect
                for point in points:
                  
                  # this loop may run for quite some time, keep GUI responsive by handling events
                  keepGuiResponsiveAndRaiseIfSimulationDone()

                  vec = Vector(point.X, point.Y, point.Z)
                  vert = Part.Vertex(point)

                  # if found intersection point has some finite distance from 
                  # origin and lies within the target face and on the line,
                  # add to candidate list
                  if ( (vec-start).Length > distTol
                        and vert.distToShape(line)[0] < distTol
                        and vert.distToShape(face)[0] < distTol):
                    intersects.append([group, face, vec, (vec-start).Length])

    # return intersection that is closest to start (if any)
    if len(intersects):
      return sorted(intersects, key=lambda e: e[-1])[0][:-1]
  
  
  def getNormal(self, nearest_part, origin, neworigin, epsLength=1e-6):
    '''
    calculate the normal vector given, inherited from OpticsWorkbench
    '''
    dRay = neworigin - origin
    if hasattr(nearest_part, 'Surface'):
      uv = nearest_part.Surface.parameter(neworigin)
      try:
        normal = nearest_part.normalAt(uv[0], uv[1])
      except Exception:
        # try to take normal in very close vicinity, hoping it is only
        # locally illdefined
        r1, r2 = [(1 if random.random()<.5 else -1)*(.1+random.random()) for _ in range(2)]
        normal = nearest_part.normalAt(uv[0] + epsLength*r1, uv[1] + epsLength*r2)
    else:
      return Vector(0, 0, 0)
    cosangle = dRay*normal / (dRay.Length*normal.Length)
    if cosangle < 0:
      return -normal, True
    return normal, False

  def mirror(self, ray, normal):
    '''
    mirror a ray at a normal vector, inherited from OpticsWorkbench
    '''
    return -(2*normal*(ray*normal) - ray)

  def snellsLaw(self, ray, n1, n2, normal):
    '''
    apply snell's law, inherited from OpticsWorkbench
    '''
    root = 1 - n1/n2 * n1/n2 * normal.cross(ray) * normal.cross(ray)
    if root < 0: # total reflection
      return self.mirror(ray, normal), True
    return n1/n2 * normal.cross( (-normal).cross(ray)) + normal * sqrt(root), False
