__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

import pytest
import time
import subprocess
import os

baseDir = os.path.abspath(os.path.dirname(__file__))

def collectNotebooks():
  # find all notebooks
  for root, dirs, files in os.walk(baseDir):
    for _f in files:
      f = (root+'/'+_f)[len(baseDir):].lstrip('/')
      if 'notest' in f or 'notest' in root or 'checkpoint' in f or 'checkpoint' in root:
        continue
      if _f.endswith('.ipynb') and '.nbconvert' not in _f:
        yield root, f, _f

allArgs = list(collectNotebooks())
@pytest.mark.parametrize('args', allArgs, ids=[a[1] for a in allArgs])
def test_runPythonNotebooks(args):
  root, f, _f = args
  print(f'running notebook {f}')
  try:
    subprocess.run(f'uv run jupyter nbconvert --ExecutePreprocessor.timeout=None '
                    f'--to notebook --execute "{_f}"',
                    cwd=root, shell=True, check=True)
  except Exception:
    raise
  else:    
    # do cleanup
    resultFile = root+'/'+_f[:-6]+'.nbconvert.ipynb'
    print(f'deleting {resultFile}...')
    os.remove(resultFile)
