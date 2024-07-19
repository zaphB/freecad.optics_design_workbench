from setuptools import setup, find_packages

# DO NOT CHANGE'
version = '0.1.3'

# read the contents of readme
import os
with open(os.path.join(os.path.dirname(__file__), 'README.md'),
          encoding='utf-8') as f:
  description = f.read()

setup(
  name='freecad.optics_design_workbench',
  version=version,
  url='https://github.com/zaphB/optics_design_workbench',
  long_description=description,
  long_description_content_type='text/markdown',
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
