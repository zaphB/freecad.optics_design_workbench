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
from ..simulation.raytracing_cache import *
from .common import *


class Ray():
  '''
  Class representing an individual ray.
  '''
  def __init__(self, lightSource, initPoint, initDirection, 
               wavelength, initPower=1, metadata={}):
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
        maxRayLength = 1000 * self.lightSource.MaxRayLengthScale
      if maxIntersections is None:
        maxIntersections = 100 * self.lightSource.MaxIntersectionsScale
      
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
                                               currentMedium=currentMedium,
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

      # update ray power if medium is absorptive
      if hasattr(prevMedium, 'AbsorptionLength'):
        _absLength = float(prevMedium.AbsorptionLength)
        if _absLength == 0:
          currentPower = 0
        elif isfinite(_absLength):
          currentPower = exp( -sqrt(sum( (prevPoint-currentPoint)**2 ))/_absLength )

      # calculate normal and whether ray is facing the object from the outside or the inside
      normal, isEntering = self.getNormal(face, prevPoint, currentPoint)

      # run onHit handler of object that caused intersection
      obj.Proxy.onRayHit(source=self.lightSource, obj=obj, 
                         point=currentPoint, direction=currentDirection, 
                         power=currentPower, isEntering=isEntering, 
                         metadata=rayMetadata, store=store)

      # set colorChange to value requested by the hit object
      if (obj.ViewObject is not None 
            and hasattr(obj.ViewObject, 'Weight') 
            and obj.ViewObject.Weight != 0 ):
        colorChange = (obj.ViewObject.Weight, obj.ViewObject.Color)
      else:
        colorChange = None

      # hit mirror: direction is mirrored at normal, 
      # medium is unchanged, power is altered according to reflectivity
      if obj.OpticalType == 'Mirror':
        # calculate direction according to ideal specular reflection
        directionSpecular = self.mirror(currentDirection, normal)

        # apply stochastic corrections and update ray direction
        currentDirection = obj.Proxy.applyStochasticRayCorrections(obj,
              directionIn = currentDirection/currentDirection.Length,
              idealDirectionOut = directionSpecular,
              normal = normal,
        )

        # reduce ray power according to reflectivity
        currentPower *= obj.Reflectivity

        # mirrors have exactly one reflection in sequential mode
        sequenceIndex += 1
           
      # hit lens: direction is altered according to Snells law,
      # medium is changed depending on whether left or entered the lens
      elif obj.OpticalType == 'Lens':
        # ray enters lens
        if isEntering:
          # from medium to medium
          if currentMedium is not None:
            n1 = currentMedium.RefractiveIndex
            currentMedium = obj
            n2 = currentMedium.RefractiveIndex

          # from vacuum to medium
          else:
            n1 = 1
            currentMedium = obj
            n2 = currentMedium.RefractiveIndex

        # ray exits lens (or may suffer total reflection)
        else:
          # currentMedium=None will only occur in rare cases, e.g. a ray just
          # touching a sharp corner of a lens, in these cases ignoring the lens
          # (because n1 is set to 1) is fine. 
          if currentMedium is None:
            n1 = 1
          else:
            n1 = currentMedium.RefractiveIndex
          n2 = 1

        # calculate scattered ray direction according to Snell's law
        refractedDirection, isTotalReflection = self.snellsLaw(
                                    currentDirection/currentDirection.Length,
                                    n1, n2, normal)

        # apply stochastic corrections and update ray direction
        currentDirection = obj.Proxy.applyStochasticRayCorrections(obj,
              directionIn = currentDirection/currentDirection.Length,
              idealDirectionOut = refractedDirection,
              normal = normal,
        )

        # if ray traveled in exit direction and not total reflection occurred,
        # set current medium to vacuum, also make sure that the ray was exiting
        # the body of the current medium
        if not isEntering and not isTotalReflection and currentMedium == obj:
          currentMedium = None

          # increment sequence index only after ray left lens 
          # (without internal reflection)
          sequenceIndex += 1

      # hit grating: direction is altered according to selected diffraction order,
      # medium never changes, entering a grating applies diffraction, leaving the
      # grating does not do anything
      elif obj.OpticalType == 'Grating':

        if obj.GratingType == 'Reflection':

          if isEntering:
            n = currentMedium.RefractiveIndex if currentMedium else 1
            currentDirection = self.lineGrating(
                                      currentDirection/currentDirection.Length,
                                      n, n, normal, obj)
            sequenceIndex += 1

          # do nothing if ray is leaving reflection grating (should never happen)
          else:
            pass
        
        elif obj.GratingType == 'Transmission':

          if isEntering:
            if currentMedium is not None:
              raise ValueError('ray entered grating while already being inside a medium, '
                               'get rid of any overlapping lenses/transmission gratings '
                               'in your project')
            n1 = 1
            currentMedium = obj
            n2 = currentMedium.RefractiveIndex
            currentDirection = self.lineGrating(
                                      currentDirection/currentDirection.Length,
                                      n1, n2, normal, obj)

          # apply lens-like refraction if ray is leaving transmission grating
          else:
            if currentMedium is None:
              n1 = 1
            else:
              n1 = currentMedium.RefractiveIndex
            n2 = 1

            # update ray direction according to Snell's law
            currentDirection, isTotalReflection = self.snellsLaw(
                                          currentDirection/currentDirection.Length,
                                          n1, n2, normal)

            # if ray traveled in exit direction and not total reflection occurred,
            # set current medium to vacuum
            if not isTotalReflection:
              currentMedium = None

              # increment sequence index only after ray left grating
              # (without internal reflection)
              sequenceIndex += 1

        else:
          raise ValueError(f'invalid grating type: {obj.GratingType=}')

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

  def findNearestIntersection(self, start, direction, currentMedium, maxRayLength, distTol=None, sequenceIndex=None):
    '''
    Find the closest relevant optical object intersecting with the ray
    of given start and direction. Start and direction are expected to be
    given in global coordinates.
    '''
    distTol = self._getDistTol(distTol)
    intersects = []
    
    # loop through all relevant optical groups
    for group in find.relevantOpticalObjects(self.lightSource, sequenceIndex=sequenceIndex):

      # IMPORTANT NOTE ON MEMORY LEAKS: This loop makes various calls that cause the memory
      # allocations on the C++ side, e.g. obj.Shape, shape.BoundBox, Part.makeLine, 
      # line.Curve, etc. Each of these calls potentially causes memory leaks because it is 
      # not possible to free this memory from the python side. Experience has shown that 
      # FreeCAD/OCC do not clean up even after many hours, only if the simulation is ended. 
      #
      # Here is what we can do to keep memory consumption under control:
      # 1) Where possible use raytracing_cache functions cachedBoundBox, cachedShape, ...
      #    These will avoid recreating any C++ objects as e.g. obj.Shape would do.
      #    This works for Shapes, Faces, Surfaces etc of static geometric objects in 
      #    the project. This is not useful for anything that depends on the current
      #    ray because it does not make sense to cache it if the next ray will be 
      #    different.
      # 2) When we have to actually recalculate geometry (e.g. Part.makeLine) ensure
      #    to explicitly use python's "del" on the variables. 
     
      # All we can do is use 'del' or let the python reference go out of scope. 
      # a small memory leak, because it  Use  where possible

      # this loop may run for quite some time, keep GUI responsive by handling events
      keepGuiResponsiveAndRaiseIfSimulationDone()

      # get global placement transform matrices from group
      gpM, gpMi = group.Proxy._calcTransforms(group)[:2]
      p = cachedPlacementMatrix(group)
      gpM = gpM*p.inverse()
      gpMi = p*gpMi

      # only care if bounding box is closer to start point than maxRayLength and 
      # if bounding box actually intersects with the ray
      if hasattr(group, 'Shape'):
        # fetch bounding box
        sbb = cachedBoundBox(cachedShape(group), enlarge=distTol)

        # find start and direction vectors in local coordinates of optical group
        lstart = gpMi*start 
        ldirection = gpMi*(start+direction)-lstart

        # create line already here because it involves a small (unavoidable) memory leak
        line = Part.makeLine(lstart, lstart+ldirection/ldirection.Length*maxRayLength)
        # check if bounding box is hit by ray
        if ( ( not isfinite(maxRayLength)
                or any([(sbb.getPoint(i)-lstart).Length < 2*maxRayLength 
                                                            for i in range(8)]) )
            and sbb.intersect(lstart, ldirection) ):
          
          # loop through all faces
          for face in cachedFaces(cachedShape(group)):

            # this loop may run for quite some time, keep GUI responsive by handling events
            keepGuiResponsiveAndRaiseIfSimulationDone()

            # only care if bounding box of face intersects with ray
            fbb = cachedBoundBox(face, enlarge=distTol)
            if fbb.intersect(lstart, ldirection):

              # find intersection points and loop through all of them
              if intersect := line.Curve.intersect(cachedSurface(face)):
                points, _ = intersect
                for point in points:

                  # this loop may run for quite some time, keep GUI responsive by handling events
                  keepGuiResponsiveAndRaiseIfSimulationDone()

                  vec = Vector(point.X, point.Y, point.Z)
                  vert = Part.Vertex(point)

                  # if found intersection point has some finite distance from 
                  # origin and lies within the target face and on the line,
                  # add to candidate list
                  if ( (vec-lstart).Length > distTol
                        and vert.distToShape(line)[0] < distTol
                        and vert.distToShape(face)[0] < distTol):
                    intersects.append([group, (gpM, gpMi, face), gpM*vec, (vec-lstart).Length])

    # return intersection that is closest to start (if any), if multiple intersections 
    # exist that are closer than 2*distTol to the the closest intersection, prefer the
    # closest, and the ones that have nothing to do with the current medium 
    minDist = inf
    result = None
    for group, face, vec, distance in sorted(intersects, key=lambda e: e[-1]):
      minDist = min([minDist, distance])
      # end loop if we are further away from closest intersection than 2*distTol
      if distance > minDist + 2*distTol:
        break
      # overwrite result if no result yet of if intersection is not with current medium
      if result is None or group != currentMedium:
        result = (group, face, vec)
      # stop looking after intersection not with current medium was found
      if group != currentMedium:
        break
    return result
  
  def getNormal(self, face, fromPoint, toPoint, epsLength=1e-6):
    '''
    calculate the normal vector given, inherited from OpticsWorkbench
    '''
    origToPoint = toPoint
    gpM, gpMi, _face = face
    fromPoint, toPoint = gpMi*fromPoint, gpMi*toPoint
    if hasattr(_face, 'Surface'):
      uv = _face.Surface.parameter(toPoint)
      try:
        normal = _face.normalAt(uv[0], uv[1])
      except Exception:
        # try to take normal in very close vicinity, hoping it is only
        # locally illdefined
        r1, r2 = [(1 if random.random()<.5 else -1)*(.1+random.random()) for _ in range(2)]
        normal = _face.normalAt(uv[0] + epsLength*r1, uv[1] + epsLength*r2)
    else:
      return Vector(0, 0, 0)
    dRay = toPoint-fromPoint
    cosangle = dRay*normal/(dRay.Length*normal.Length)
    #print(f'normal before: {normal=}')
    normal = gpM*(toPoint+normal)-origToPoint
    #print(f'normal after: {normal=}')
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

  def lineGrating(self, ray, n1, n2, normal, obj):  # from Ludwig 1970
    wavelength = self.initWavelength
    order = obj.GratingDiffractionOrder
    lpm = obj.GratingLinesPerMillimeter
    g_g_p_vector = obj.GratingLinesOrientation

    # get parameters
    wavelength = wavelength / 1000
    ray = ray / ray.Length
    surf_norma = normal
    surf_norma = surf_norma / surf_norma.Length  # normalize the surface normal
    # hypothetical first vector determining the orientation of the grating rules. 
    # This vector is normal to a plane that would cause the rules by intersection 
    # with the surface of the grating.
    g_g_p_vector = g_g_p_vector / g_g_p_vector.Length

    P = g_g_p_vector.cross(surf_norma)
    P = P / P.Length
    D = surf_norma.cross(P)
    D = D / D.Length
    mu = n1 / n2
    d = 1000 / lpm
    T = (order * wavelength) / (n1 * d)
    V = (mu * (ray[0] * surf_norma[0] + ray[1] * surf_norma[1] +
                ray[2] * surf_norma[2])) / surf_norma.dot(surf_norma)
    W = (mu**2 - 1 + T**2 - 2 * mu * T *
          (ray[0] * D[0] + ray[1] * D[1] + ray[2] * D[2])
          ) / surf_norma.dot(surf_norma)
    Q = ((-2 * V + ((2 * V)**2 - 4 * W)**0.5) / 2,
          (-2 * V - ((2 * V)**2 - 4 * W)**0.5) / 2)

    if obj.GratingType == 'Reflection':
      S_0 = mu * ray[0] - T * D[0] + max(Q) * surf_norma[0]
      S_1 = mu * ray[1] - T * D[1] + max(Q) * surf_norma[1]
      S_2 = mu * ray[2] - T * D[2] + max(Q) * surf_norma[2]
    elif obj.GratingType == 'Transmission':
      S_0 = mu * ray[0] - T * D[0] + min(Q) * surf_norma[0]
      S_1 = mu * ray[1] - T * D[1] + min(Q) * surf_norma[1]
      S_2 = mu * ray[2] - T * D[2] + min(Q) * surf_norma[2]
    else:
      raise ValueError(f'unexpected {obj.GratingType=}')

    return -Vector(S_0, S_1, S_2)
