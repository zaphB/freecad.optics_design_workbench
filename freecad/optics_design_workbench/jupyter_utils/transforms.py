from numpy import *

def applyTransformation(points, transform):
  matrix, translate = transform[:3,:3], transform[:3,3:]
  return ( matrix.dot( points.T ) + translate ).T

def applyTransformationWithoutTranslation(points, transform):
  return ( transform[:3,:3].dot( points.T ) ).T
