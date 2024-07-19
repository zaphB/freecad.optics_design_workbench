__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
__doc__ = '''

'''.strip()


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
from .common import *

class Ray():
  '''
  Class representing an individual ray.
  '''
  def __init__(self, lightSource, startingPoint, direction, initPower=1):
    self.lightSource = lightSource
    self.startingPoint = startingPoint
    self.direction = direction
    self.initPower = initPower
     
  def traceRay(self, powerTol=1e-6, maxRayLength=None,
               maxIntersections=None, store=False):
    '''
    Find all reflection/refraction/detection points of this ray. Returns a
    generator that yields (p1,p2), power, medium tuples. p1, p2 are two
    vectors describing a ray segment. power is the ray power at p1. medium
    is None for vacuum or the FreeCAD object if the ray is traveling through
    and optical object.
    '''
    # calc limits
    if find.activeSimulationSettings():
      if maxRayLength is None:
        maxRayLength = ( self.lightSource.MaxRayLengthScale 
                          * find.activeSimulationSettings().MaxRayLength )
      if maxIntersections is None:
        maxIntersections = (self.lightSource.MaxIntersectionsScale
                              *find.activeSimulationSettings().MaxIntersections )
    else:
      if maxRayLength is None:
        maxRayLength = 100 * self.lightSource.MaxRayLengthScale
      if maxIntersections is None:
        maxIntersections = 10 * self.lightSource.MaxIntersectionsScale
    numIntersections = 0
    
    # variables to store current state during intersection finder loop
    prevPoint, currentPoint = self.startingPoint, self.startingPoint
    currentDirection = self.direction
    prevMedium, currentMedium = None, None
    prevPower, currentPower = self.initPower, self.initPower
    while True:
      # this loop may run for quite some time, keep GUI responsive by handling events
      processGuiEvents()
      
      # stop tracing if maxIntersections limit is reached
      if numIntersections >= maxIntersections:
        break
      numIntersections += 1

      # find next intersection
      intersect = self.findNearestIntersection(currentPoint, currentDirection, maxRayLength=maxRayLength)
      if intersect is None:
        # if no intersection is found yield segment with maxLength and exit loop
        yield ((currentPoint, currentDirection/currentDirection.Length*maxRayLength), 
                currentPower, currentMedium)
        break
      obj, face, point = intersect

      # update current state
      prevPoint, prevPower, prevMedium = currentPoint, currentPower, currentMedium
      currentPoint = point

      # add yield latest segment
      yield (prevPoint, currentPoint), prevPower, prevMedium

      # calculate normal and wether ray is facing the object from the outside or the inside
      normal, isEntering = self.getNormal(face, prevPoint, currentPoint)

      # run onHit handler of object that caused intersection
      obj.Proxy.onRayHit(source=self.lightSource, obj=obj, point=currentPoint, 
                         power=currentPower, isEntering=isEntering, store=store)

      # hit mirror: direction is mirrored at normal, 
      # medium is unchanged, power is altered according to reflectivity
      if obj.OpticalType == 'Mirror':
        currentDirection = self.mirror(currentDirection, normal)
        currentPower *= obj.Reflectivity
           
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

        # if ray traveled in exit direction and not total reflection occured,
        # set current medium to vacuum
        if not isEntering and not isTotalReflection:
          currentMedium = None
            
      # hit absorber: intensity is changed / ray is ended if intensity below min
      elif obj.OpticalType == 'Absorber':
        currentPower = 0

      # hit vacuum: do nothing at all to direction / intensity
      elif obj.OpticalType == 'Vacuum':
        pass
            
      # end if beam died
      if currentPower < powerTol:
        break
  

  def findNearestIntersection(self, start, direction, maxRayLength, distTol=1e-6):
    '''
    Find the closest relevant optical object intersecting with the ray
    of given start and direction.
    '''
    line = Part.makeLine(start, start+direction/direction.Length*maxRayLength)
    intersects = []
    
    # loop through all relevant optical groups
    for group in find.relevantOpticalObjects(self.lightSource):

      # this loop may run for quite some time, keep GUI responsive by handling events
      processGuiEvents()

      # only care if bounding box is closer to start point than maxRayLength and 
      # if bounding box actually intersects with the ray
      if (hasattr(group, 'Shape')
            and ( not isfinite(maxRayLength)
                      or any([(group.Shape.BoundBox.getPoint(i)-start).Length
                                                          < maxRayLength 
                                                                for i in range(8)]) )
            and group.Shape.BoundBox.intersect(start, direction) ):

        # loop through all faces
        for face in group.Shape.Faces:

          # this loop may run for quite some time, keep GUI responsive by handling events
          processGuiEvents()

          # only care if bounding box of face intersects with ray
          if face.BoundBox.intersect(start, direction):

            # find intersection points and loop through all of them
            if intersect := line.Curve.intersect(face.Surface):
              points, _ = intersect
              for point in points:
                
                # this loop may run for quite some time, keep GUI responsive by handling events
                processGuiEvents()

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
  
  
  def getNormal(self, nearest_part, origin, neworigin, distTol=1e-6):
    '''
    calculate the normal vector given, inherited from OpticsWorkbench, needs cleaning
    '''
    dRay = neworigin - origin
    if hasattr(nearest_part, 'Curve'):
      param = nearest_part.Curve.parameter(neworigin)
      tangent = nearest_part.tangentAt(param)
      normal1 = dRay.cross(tangent)
      normal = tangent.cross(normal1)
      if normal.Length < distTol:
        return Vector(0, 0, 0)
      normal = normal / normal.Length
    elif hasattr(nearest_part, 'Surface'):
      uv = nearest_part.Surface.parameter(neworigin)
      normal = nearest_part.normalAt(uv[0], uv[1])
    else:
      return Vector(0, 0, 0)
    cosangle = dRay*normal / (dRay.Length*normal.Length)
    if cosangle < 0:
      return -normal, True
    return normal, False

  def mirror(self, ray, normal):
    return -(2*normal*(ray*normal) - ray)

  def snellsLaw(self, ray, n1, n2, normal):
    root = 1 - n1/n2 * n1/n2 * normal.cross(ray) * normal.cross(ray)
    if root < 0: # total reflection
      return self.mirror(ray, normal), True
    return n1/n2 * normal.cross( (-normal).cross(ray)) + normal * sqrt(root), False
