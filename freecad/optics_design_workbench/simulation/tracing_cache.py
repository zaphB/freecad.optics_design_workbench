'''
This module implements a cache for various attributes of FreeCAD objects.
This cache is necessary because reading e.g. the BoundBox property of one 
and the same FreeCAD object multiple times creates memory leaks. Try 
running the following in a FreeCAD shell:

```
for _ in range(100000):
  App.ActiveDocument.Sphere.Shape.BoundBox
```

This will cause a measurable memory usage increase. Because the ray-tracing
loop uses Shape, BoundBox and others massively, caching is required to make 
sure not to ask FreeCAD for these attributes every time they are needed. 
'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'


import time

from .. import io

_CACHE_LUT = {}
_LAST_SIZE_REPORT = None
_CACHED_PROPERTY_CALLS = 0
_ADDED_TO_CACHE_CALLS = 0
_DELETED_BECAUSE_ENLARGE_MISMATCH = 0
_SIZE_REPORT_INTERVAL = 600

def cacheClear():
  global _CACHE_LUT, _LAST_SIZE_REPORT, _CACHED_PROPERTY_CALLS, _ADDED_TO_CACHE_CALLS, _DELETED_BECAUSE_ENLARGE_MISMATCH
  io.verb(f'tracing_cache: cleared')
  _LAST_SIZE_REPORT = time.time()
  _CACHED_PROPERTY_CALLS = 0
  _ADDED_TO_CACHE_CALLS = 0
  _DELETED_BECAUSE_ENLARGE_MISMATCH = 0
  _CACHE_LUT = {}

def cachedProperty(obj, prop, enlarge=None):
  global _LAST_SIZE_REPORT, _CACHED_PROPERTY_CALLS, _ADDED_TO_CACHE_CALLS, _DELETED_BECAUSE_ENLARGE_MISMATCH

  # if cache entry exists but enlargement differs from requested value -> drop cached entry
  if (prop in _CACHE_LUT.keys() 
      and obj in _CACHE_LUT[prop].keys() 
      and _CACHE_LUT[prop][obj].get('wasEnlarged', None) != enlarge ):
    _DELETED_BECAUSE_ENLARGE_MISMATCH += 1
    _CACHE_LUT[prop].pop(obj)

  # create cache entry if not existing
  if prop not in _CACHE_LUT.keys():
    _CACHE_LUT[prop] = {}
  if obj not in _CACHE_LUT[prop].keys():
    _CACHE_LUT[prop][obj] = dict(obj=getattr(obj, prop))
    _ADDED_TO_CACHE_CALLS += 1
    # apply enlargement:
    if enlarge:
      _CACHE_LUT[prop][obj]['obj'].enlarge(enlarge)
      _CACHE_LUT[prop][obj]['wasEnlarged'] = enlarge
  else:
    _CACHED_PROPERTY_CALLS += 1

  # check if its time to report
  if _LAST_SIZE_REPORT is None:
    _LAST_SIZE_REPORT = time.time()
  if time.time()-_LAST_SIZE_REPORT > _SIZE_REPORT_INTERVAL:
    io.verb(f'tracing_cache: {len(_CACHE_LUT)} different properties '
            f'cached, {", ".join([str(len(e)) for e in _CACHE_LUT.values()])} '
            f'elements cached for each property respectively, '
            f'stats since last trace_cache log: {1e-6*_CACHED_PROPERTY_CALLS:.1e} '
            f'({_CACHED_PROPERTY_CALLS/(time.time()-_LAST_SIZE_REPORT):.1e}/s) properties requested, '
            f'{1e2*(_CACHED_PROPERTY_CALLS-_ADDED_TO_CACHE_CALLS)/_CACHED_PROPERTY_CALLS:.0f}'
            f'% cached responses, '
            f'{_DELETED_BECAUSE_ENLARGE_MISMATCH:.1e} properties deleted because enlarge mismatched')
    _LAST_SIZE_REPORT = time.time()
    _CACHED_PROPERTY_CALLS = 0
    _ADDED_TO_CACHE_CALLS = 0

  # return cached result
  return _CACHE_LUT[prop][obj]['obj']

def cachedShape(obj):
  return cachedProperty(obj, 'Shape')

def cachedFaces(obj):
  return cachedProperty(obj, 'Faces')

def cachedBoundBox(obj, enlarge=None):
  return cachedProperty(obj, 'BoundBox', enlarge=enlarge)
  
def cachedViewObject(obj):
  return cachedProperty(obj, 'ViewObject')
