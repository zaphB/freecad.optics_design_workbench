import pytest
import os

def pytest_generate_tests(metafunc):
  for _ in range(20):
    latestAppImage = "latest-freecad.AppImage"
    if os.path.exists(latestAppImage):
      break
    latestAppImage = '../'+latestAppImage
  else:
    raise ValueError(f'failed to find latest-freecad.AppImage, did you run ./dev/download-latest-appimage.sh? ({os.path.abspath('.')=})')
  metafunc.parametrize("envValue", ["", os.path.abspath(latestAppImage)], indirect=True)

@pytest.fixture(autouse=True)
def envValue(request, monkeypatch):
  param = getattr(request, "param", None)
  if param is not None:
    print(f'setting TEST_FREECAD_BINARY to {repr(param)}')
    monkeypatch.setenv('TEST_FREECAD_BINARY', param)
  yield param
