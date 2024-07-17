#!/usr/bin/env python3

import unittest
import time
import subprocess
import os

class TestRunNotebooks(unittest.TestCase):
  def test_testRunNotebooks(self):
    baseDir = os.path.abspath(os.path.dirname(__file__))

    # find all notebooks and run them
    for root, dirs, files in os.walk(baseDir):
      if 'freecad_tests' in root:
        continue
      for f in files:
        if f.endswith('.ipynb') and not f.endswith('.nbconvert.ipynb'):
          with self.subTest(f):
            subprocess.run(f'jupyter nbconvert '
                  f'--ExecutePreprocessor.timeout=None '
                  f'--to notebook --execute "{f}"',
                  cwd=root, shell=True, check=True)

if __name__ == '__main__':
  unittest.main()
