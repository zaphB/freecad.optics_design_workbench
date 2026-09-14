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
  
  # LD_PRELOAD workaround: LD_PRELOAD prefix is necessary on my dev-machine to launch appimage, otherwise it will die with GLX loading error
  metafunc.parametrize('envValue', ['', f'LD_PRELOAD=/usr/lib/libdrm_amdgpu.so.1 {os.path.abspath(latestAppImage)}'], indirect=True)

@pytest.fixture(autouse=True)
def envValue(request, monkeypatch):
  param = getattr(request, "param", None)
  if param is not None and param.strip():
    _s = param.split()
    bina = _s.pop(-1)
    envs = ' '.join(_s)
    print(f'setting TEST_FREECAD_BINARY to {repr(bina)}, with env vars: {repr(envs)}')
    monkeypatch.setenv('TEST_FREECAD_BINARY', bina)
    monkeypatch.setenv('TEST_FREECAD_ENVS', envs)
  yield param
