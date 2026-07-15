__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'

from numpy import *
import pytest
import os

from optics_design_workbench import jupyter_utils

baseDir = os.path.abspath(os.path.dirname(__file__))

def test_allPlacementsAndPaths():
  
  # open GUI for debugging if needed
  #jupyter_utils.openFreecadGui(f'{baseDir}/main.FCStd')

  with jupyter_utils.FreecadDocument(f'{baseDir}/main.FCStd') as f:

    # just printing some paths and make sure nothing crashes
    print( f.OpticalPointSource001.Placement.get() )
    print('-')
    print('shifted cube:')
    for line in f.execInFreecadShellIter('''
      from freecad.optics_design_workbench import freecad_elements
      for pl,path in freecad_elements.allPlacementsAndPaths( App.activeDocument().getObjectsByLabel('ShiftedCube')[0] ):
        print(freecad_elements.prettyPath(path))
        print('total placement:', pl)
        print('.')
    '''):
      print(line)
    print('-')
    print('shifted cube link:')
    for line in f.execInFreecadShellIter('''
      from freecad.optics_design_workbench import freecad_elements
      for pl,path in freecad_elements.allPlacementsAndPaths( App.activeDocument().getObjectsByLabel('ylink')[0] ):
        print(freecad_elements.prettyPath(path))
        print('total placement:', pl)
        print('.')
    '''):
      print(line)
    print('-')

    # assert strict values for placements
    matrices = [
      array(((1,0,0,0),(0,1,0,0),(0,0,1,-100),(0,0,0,1))),
      array(((1,0,0,3),(0,1,0,3),(0,0,1,-100),(0,0,0,1))),
      array(((1,0,0,3),(0,1,0,0),(0,0,1,-100),(0,0,0,1))),
      array(((1,0,0,3),(0,1,0,-27),(0,0,1,-100),(0,0,0,1))),
      array(((1,0,0,3),(0,1,0,-27),(0,0,1,-100),(0,0,0,1))),
      array(((1,0,0,3),(0,1,0,3),(0,0,1,-97),(0,0,0,1))),
      array(((1,0,0,0),(0,1,0,0),(0,0,1,-100),(0,0,0,1))),
      array(((1,0,0,0),(0,1,0,-30),(0,0,1,-100),(0,0,0,1))),
    ]
    i = 0
    differingMats = []
    for line in f.execInFreecadShellIter(r'''
      from freecad.optics_design_workbench import freecad_elements
      for pl,path in freecad_elements.allPlacementsAndPaths( App.activeDocument().getObjectsByLabel('ShiftedCube')[0] ):
        print(freecad_elements.prettyPath(path))
        print(freecad_elements.matrixToString(pl.toMatrix()))
        print('.')
    '''):
      if line.startswith('array'):
        print(line)
        mat = eval(line)
        if not (isclose(mat, matrices[i])).all():
          differingMats.append([i, mat, matrices[i]])
        i += 1
      #else:
      #  print(line)
    print('-')
    if len(differingMats):
      raise ValueError('found unexpected placement matrices:\n\n'+'\n\n'.join(
                [ f'{i=}, found=\n{found}\nexpect=\n{expect}' for i,found,expect in differingMats]
      ))
