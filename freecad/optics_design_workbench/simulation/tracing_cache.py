'''
This module implements a cache for various attributes of FreeCAD objects.
Such a cache is necessary simply because using e.g. the BoundBox property
of one and the same object multiple times creates memory leaks. Try running
the following in a FreeCAD shell:

```
for _ in range(100000):
  App.ActiveDocument.Sphere.Shape.BoundBox
```

This will cause a measurable memory usage increase. Because the ray-tracing
loop uses Shape, BoundBox and other massively, cache is required to make 
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
_SIZE_REPORT_INTERVAL = 600

def cacheClear():
  global _CACHE_LUT, _LAST_SIZE_REPORT, _CACHED_PROPERTY_CALLS, _ADDED_TO_CACHE_CALLS
  io.verb(f'tracing_cache: cleared')
  _LAST_SIZE_REPORT = time.time()
  _CACHED_PROPERTY_CALLS = 0
  _ADDED_TO_CACHE_CALLS = 0
  _CACHE_LUT = {}

def cachedProperty(obj, prop):
  global _LAST_SIZE_REPORT, _CACHED_PROPERTY_CALLS, _ADDED_TO_CACHE_CALLS

  # create cache entry if not existing
  if prop not in _CACHE_LUT.keys():
    _CACHE_LUT[prop] = {}
  if obj not in _CACHE_LUT[prop].keys():
    _CACHE_LUT[prop][obj] = getattr(obj, prop)
    _ADDED_TO_CACHE_CALLS += 1
  else:
    _CACHED_PROPERTY_CALLS += 1

  # check if its time to report
  if _LAST_SIZE_REPORT is None:
    _LAST_SIZE_REPORT = time.time()
  if time.time()-_LAST_SIZE_REPORT > _SIZE_REPORT_INTERVAL:
    io.verb(f'tracing_cache: {len(_CACHE_LUT)} different properties '
            f'cached, {", ".join([str(len(e)) for e in _CACHE_LUT.values()])} '
            f'elements cached for each property respectively, '
            f'stats since last trace_cache log: {1e-6*_CACHED_PROPERTY_CALLS:.0f}M '
            f'({_CACHED_PROPERTY_CALLS/(time.time()-_LAST_SIZE_REPORT):.1e}/s) properties requested, '
            f'{1e2*(_CACHED_PROPERTY_CALLS-_ADDED_TO_CACHE_CALLS)/_CACHED_PROPERTY_CALLS:.2f}'
            f'% cached responses')
    _LAST_SIZE_REPORT = time.time()
    _CACHED_PROPERTY_CALLS = 0
    _ADDED_TO_CACHE_CALLS = 0

  # return cached result
  return _CACHE_LUT[prop][obj]

def cachedShape(obj):
  return cachedProperty(obj, 'Shape')

def cachedFaces(obj):
  return cachedProperty(obj, 'Faces')

def cachedBoundBox(obj):
  return cachedProperty(obj, 'BoundBox')
  
def cachedViewObject(obj):
  return cachedProperty(obj, 'ViewObject')
