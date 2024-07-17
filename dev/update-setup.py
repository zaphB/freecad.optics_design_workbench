#!/usr/bin/env python3

import subprocess
import re
import sys
from os import path

cwd = path.join(path.dirname(__file__), '..')

# run git update-index to find uncommitted changes
if subprocess.run('git update-index --refresh'.split(),
                  stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL,
                  cwd=cwd).returncode not in (0, 1):
  raise RuntimeError('failed to run "git update-index"')

# as default, take latest release tag as version number and
# add the current commit tag as local tag
versionTags = (['v0.0.0']
              + list(filter(lambda t: re.match(r'v\d+\.\d+\.\d+', t),
                     subprocess.run('git tag --sort=committerdate'.split(),
                                     cwd=cwd,
                                     capture_output=True)
                                         .stdout.decode().split('\n'))))

# try to read current version from setup.py and add to versionTags list
# if it is newer than latest tagged version
m = re.search(r"version\s*=\s*['\"](\d+)\.(\d+)\.(\d+)+?.*['\"]",
              open(path.join(cwd, 'setup.py')).read())
if m:
  ep, major, minor = [int(i) for i in m.groups()]
  _ep, _major, _minor = [int(i) for i in versionTags[-1][1:].split('.')]
  if (ep>_ep
        or (ep==_ep and major>_major)
        or (ep==_ep and major==_major and minor>_minor)):
    versionTags.append(f'v{ep}.{major}.{minor}')

commitHash = subprocess.run('git rev-parse --short HEAD'.split(),
                            capture_output=True,
                            cwd=cwd).stdout.decode().strip()

version = f'{versionTags[-1][1:]}+h{commitHash}'

# if current commit is tagged as release, set release version
v = subprocess.run([*'git tag --points-at'.split(),
                   subprocess.run('git branch --show-current'.split(),
                                  capture_output=True,
                                  cwd=cwd).stdout.strip()],
                   capture_output=True,
                   cwd=cwd).stdout.decode()
if v:
  versionTags = list(filter(lambda t: re.match(r'v\d+\.\d+', t),
                            v.split()))
  if len(versionTags) == 1:
    version = versionTags[0][1:]

# if uncommitted changes exist in sollzustand subfolder, add '-mod' to version
isModified = False
for line in subprocess.run('git status --porcelain=v1'.split(),
                           cwd=cwd,
                           capture_output=True).stdout.decode().split('\n'):
  if line.strip():
    _path = line.strip().split()[-1]
    if _path.strip().startswith('sollzustand'):
      isModified = True
if isModified:
  version += ('+' if '+' not in version else '')+'mod'

# if --clean option is present, remove all version number extensions
if '--clean' in sys.argv:
  m = re.search(r'\d+\.\d+\.\d+', version)
  version = m.string[m.start():m.end()]

# replace in setup.py
result = []
replaceNextLine = False
for line in open(path.join(cwd, 'setup.py')):
  if replaceNextLine:
    result.append(f"version = '{version}'\n")
    replaceNextLine = False
  else:
    result.append(line)

  if line.strip().startswith('# DO NOT CHANGE'):
    replaceNextLine = True
open(path.join(cwd, 'setup.py'), 'w').write(''.join(result))

# replace in __init__.py
result = []
replaceNextLine = False
for line in open(path.join(cwd, 'freecad/exp_optics_workbench/__init__.py')):
  if replaceNextLine:
    result.append(f"__version__ = '{version}'\n")
    replaceNextLine = False
  else:
    result.append(line)

  if line.strip().startswith('# DO NOT CHANGE'):
    replaceNextLine = True
open(path.join(cwd, 'freecad/exp_optics_workbench/__init__.py'), 'w').write(''.join(result))

# print version to stdout
print(version)

