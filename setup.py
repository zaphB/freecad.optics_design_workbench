from setuptools import setup, find_packages

# DO NOT CHANGE: this line will be replaced by dev-update-setup.py
version = '0.0.8'

setup(
  name='freecad.exp_optics_workbench',
  version=version,
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
