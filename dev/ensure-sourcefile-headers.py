#!/bin/env python3

import os

HEADER = """'''

'''

__license__ = 'LGPL-3.0-or-later'
__copyright__ = 'Copyright 2024  W. Braun (epiray GmbH)'
__authors__ = 'P. Bredol'
__url__ = 'https://github.com/zaphB/freecad.optics_design_workbench'
""".strip()

FILENAME_BLACKLIST = ('setup.py',)
DIRNAME_BLACKLIST  = ('.git', 'dev', 'build', 'releases', 'container-home')
SRC_SUFFIXES       = ('.py',)

def conf(msg, default=None):
  if default is None:
    msg += ' (y/n)'
  elif default:
    msg += ' (Y/n)'
  else:
    msg += ' (y/N)'
  res = None
  while res is None:
    print(msg, end=' ')
    i = input()
    if '\n' in msg:
      print()
    if i.strip() == '':
      res = default
    elif i.strip().lower() in ('y', 'yes'):
      res = True
    elif i.strip().lower() in ('n', 'no'):
      res = False
    if res is None:
      print('invalid input, expecting (y)es or (n)o\n')
  return res

def main():
  for r, ds, fs in os.walk(os.path.dirname(__file__)+'/..', topdown=True):
    ds[:] = [d for d in ds if d not in DIRNAME_BLACKLIST]
    for f in fs:
      if any([f.endswith(suff) for suff in SRC_SUFFIXES]) and f not in FILENAME_BLACKLIST:
        with open(f'{r}/{f}') as _f:
          content = _f.read()
        if HEADER[-30:] not in content:
          path = os.path.relpath(f'{r}/{f}', start=os.path.dirname(__file__)+'/..')
          if conf(f'found source file {path} with missing header, insert?', default=True):
            with open(f'{r}/{f}', 'w') as _f:
              _f.write(HEADER+'\n')
              if content.strip():
                _f.write('\n\n')
              _f.write(content)

if __name__ == '__main__':
  main()
  print('done')
