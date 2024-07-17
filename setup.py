from setuptools import setup, find_packages

import os
with open(os.path.dirname(__file__)+'/freecad/optics_design_workbench/version.py') as f:
  version = f.read().split('=')[-1].strip().strip('\'"')

setup(
  name='freecad.exp_optics_workbench',
  version=version,
  url='https://github.com/zaphB/optics_design_workbench',
  author='Philipp Bredol',
  author_email='philipp.bredol@rwth-aachen.de',
  description='Physically accurate forward ray tracing for optics simulation and optimization with FreeCAD workbench frontend',
  packages=find_packages(),    
  install_requires=[
    'numpy',
    'scipy',
    'matplotlib',
    'atomicwrites'
  ],
  include_package_data=True
)
