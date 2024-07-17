from setuptools import setup, find_packages
from . import version

setup(
  name='freecad.exp_optics_workbench',
  version=version.__version__,
  url='https://github.com/zaphB/...',
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
