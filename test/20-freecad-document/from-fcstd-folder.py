__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import pytest
import os

from optics_design_workbench import jupyter_utils

# run all tests in this module with cwd set to the directory of this test
@pytest.fixture(autouse=True)
def changeTestDir(monkeypatch):
  p = os.path.dirname(__file__)
  print(f'running test in folder {p}')
  monkeypatch.chdir(p)


# open/close tests

def test_openCloseWithPath():
  with jupyter_utils.FreecadDocument(f'simple.FCStd') as f:
    pass

def test_openCloseWithoutPath():
  with jupyter_utils.FreecadDocument() as f:
    pass

def test_openCloseWithFolderName(monkeypatch):
  dirname = os.path.basename(os.path.abspath('.'))
  monkeypatch.chdir('..')
  with jupyter_utils.FreecadDocument(dirname) as f:
    pass

def test_openCloseWithPathTempCopy():
  with jupyter_utils.FreecadDocument(f'simple.FCStd', workInTempCopy=True) as f:
    pass

def test_openCloseWithoutPathTempCopy():
  with jupyter_utils.FreecadDocument(workInTempCopy=True) as f:
    pass

def test_openCloseWithFolderNameTempCopy(monkeypatch):
  dirname = os.path.basename(os.path.abspath('.'))
  monkeypatch.chdir('..')
  with jupyter_utils.FreecadDocument(dirname, workInTempCopy=True) as f:
    pass


# property access tests

# run once with workInTempCopy and once without
@pytest.fixture(params=[True,False])
def f(request):
  with jupyter_utils.FreecadDocument(workInTempCopy=request.param) as f:
    if request.param:
      print('working in temp copy')
    else:
      print('working in live file')
    yield f

# run tests once just as is and once with open/close document in between
# to make sure changes are persistent
@pytest.fixture(params=[True,False])
def openClose(f, request):
  if request.param:
    print('running without close/reopen')
    yield lambda: None
  else:
    def _closeOpen():
      f.close()
      f.open()
    print('running with close/reopen')
    yield _closeOpen

def test_setGetPlacementLabel(f, openClose):
  r = random.random()
  f.labeledBox.Placement.Base = [1,2,r]
  openClose()
  assert isclose(f.labeledBox.Placement.Base.get(), [1,2,r], rtol=1e-4).all()

def test_setGetPlacementInternalName(f, openClose):
  r = random.random()
  f.Box.Placement.Base = [1,2,r]
  openClose()
  assert isclose(f.Box.Placement.Base.get(), [1,2,r], rtol=1e-4).all()

def test_setGetSource(f, openClose):
  dens = 'exp(-theta**2/(1e-2)**2)'
  f.src.PowerDensity = dens
  openClose()
  assert f.src.PowerDensity.get() == dens

def test_setGetSetting(f, openClose):
  r = 1000*random.random()
  f.cfg.MaxRayLength = r
  openClose()
  assert f.cfg.MaxRayLength.get() == r

def test_setGetSketchConstraintViaItem(f, openClose):
  r = 5*random.random()
  f.Sketch.getConstraintsByName()['namedConstraint'] = r
  openClose()
  assert isclose(f.Sketch.getConstraintsByName()['namedConstraint'].get(), r, rtol=1e-4)

def test_setGetSketchConstraintViaAttr(f, openClose):
  r = 5*random.random()
  f.Sketch.getConstraintsByName().namedConstraint = r
  openClose()
  assert isclose(f.Sketch.getConstraintsByName().namedConstraint.get(), r, rtol=1e-4)

def test_setGetSketchConstraintViaSetter(f, openClose):
  r = 5*random.random()
  f.Sketch.getConstraintsByName().namedConstraint.set(r)
  openClose()
  assert isclose(f.Sketch.getConstraintsByName().namedConstraint.get(), r, rtol=1e-4)

def test_setGetSketchConstraintViaShorthandItem(f, openClose):
  r = 5*random.random()
  f.Sketch.ConstraintsByName['namedConstraint'] = r
  openClose()
  assert isclose(f.Sketch.ConstraintsByName['namedConstraint'].get(), r, rtol=1e-4)

def test_setGetSketchConstraintViaShorthandAttr(f, openClose):
  r = 5*random.random()
  f.Sketch.ConstraintsByName.namedConstraint = r
  openClose()
  assert isclose(f.Sketch.ConstraintsByName.namedConstraint.get(), r, rtol=1e-4)

def test_setGetSketchConstraintViaShorthandSetter(f, openClose):
  r = 5*random.random()
  f.Sketch.ConstraintsByName.namedConstraint.set(r)
  openClose()
  assert isclose(f.Sketch.ConstraintsByName.namedConstraint.get(), r, rtol=1e-4)
