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
_DELETED_BECAUSE_ARGS_MISMATCH = 0
_SIZE_REPORT_INTERVAL = 600

def cacheClear():
  global _CACHE_LUT, _LAST_SIZE_REPORT, _CACHED_PROPERTY_CALLS, _ADDED_TO_CACHE_CALLS, _DELETED_BECAUSE_ARGS_MISMATCH
  io.verb(f'raytracing_cache: cleared')
  _LAST_SIZE_REPORT = time.time()
  _CACHED_PROPERTY_CALLS = 0
  _ADDED_TO_CACHE_CALLS = 0
  _DELETED_BECAUSE_ARGS_MISMATCH = 0
  _CACHE_LUT = {}

def cachedProperty(obj, prop, method=None, args=(), isMethodInPlace=False):
  global _LAST_SIZE_REPORT, _CACHED_PROPERTY_CALLS, _ADDED_TO_CACHE_CALLS, _DELETED_BECAUSE_ARGS_MISMATCH

  # if cache entry exists but method was applied and args differ from cached result -> drop cached entry
  key = prop
  if method is not None:
    key = prop+'-'+method
    if (key in _CACHE_LUT.keys()
        and obj in _CACHE_LUT[key].keys()
        and _CACHE_LUT[key][obj].get('args', ()) != args ):
      _DELETED_BECAUSE_ARGS_MISMATCH += 1
      _CACHE_LUT[key].pop(obj)

  # create cache entry if not existing
  if key not in _CACHE_LUT.keys():
    _CACHE_LUT[key] = {}
  if obj not in _CACHE_LUT[key].keys():
    _CACHE_LUT[key][obj] = dict(obj=getattr(obj, prop))
    _ADDED_TO_CACHE_CALLS += 1
    # apply method:
    if method:
      if isMethodInPlace:
        getattr(_CACHE_LUT[key][obj]['obj'], method)(*args)
      else:
        _CACHE_LUT[key][obj]['obj'] = getattr(_CACHE_LUT[key][obj]['obj'], method)(*args)
      _CACHE_LUT[key][obj]['args'] = args
  else:
    _CACHED_PROPERTY_CALLS += 1

  # check if its time to report
  if _LAST_SIZE_REPORT is None:
    _LAST_SIZE_REPORT = time.time()
  if time.time()-_LAST_SIZE_REPORT > _SIZE_REPORT_INTERVAL:
    io.verb(f'raytracing_cache: {len(_CACHE_LUT)} different properties '
            f'cached, {", ".join([str(len(e)) for e in _CACHE_LUT.values()])} '
            f'elements cached for each property respectively, '
            f'\n'
            f'stats since last trace_cache log: {_CACHED_PROPERTY_CALLS:.1e} '
            f'({_CACHED_PROPERTY_CALLS/(time.time()-_LAST_SIZE_REPORT):.1e}/s) properties requested, '
            f'{1e2*(_CACHED_PROPERTY_CALLS-_ADDED_TO_CACHE_CALLS)/_CACHED_PROPERTY_CALLS:.0f}'
            f'% cached responses, '
            f'{_DELETED_BECAUSE_ARGS_MISMATCH:.1e} properties deleted because enlarge mismatched')
    _LAST_SIZE_REPORT = time.time()
    _CACHED_PROPERTY_CALLS = 0
    _ADDED_TO_CACHE_CALLS = 0

  # return cached result
  return _CACHE_LUT[key][obj]['obj']

def cachedShape(obj):
  return cachedProperty(obj, 'Shape')

def cachedPlacementMatrix(obj):
  return cachedProperty(obj, 'Placement', method='toMatrix')

def cachedFaces(obj):
  return cachedProperty(obj, 'Faces')

def cachedSurface(obj):
  return cachedProperty(obj, 'Surface')

def cachedBoundBox(obj, enlarge=None):
  return cachedProperty(obj, 'BoundBox', method='enlarge', args=(enlarge,), isMethodInPlace=True)
  
def cachedViewObject(obj):
  return cachedProperty(obj, 'ViewObject')
