__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

import pytest
import os
import subprocess

baseDir = os.path.abspath(os.path.dirname(__file__))

def test_buildDocs():
  for _ in range(99):
    if os.path.exists('.venv') and os.path.exists('pyproject.toml'):
      break
    os.chdir('..')
  subprocess.run(f'./dev/build-docs.sh', shell=True, check=True)
