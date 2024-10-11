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
version = f'{versionTags[-1][1:]}'

# replace date and version in package.xml
import time
for replaceStart, replaceLine in [('<version>', f'  <version>{version}</version>'),
                                  ('<date>', time.strftime('  <date>%Y-%m-%d</date>'))]:
  result = []
  for line in open(path.join(cwd, 'package.xml')):
    if line.strip().startswith(replaceStart):
      result.append(replaceLine+'\n')
    else:
      result.append(line)
  open(path.join(cwd, 'package.xml'), 'w').write(''.join(result))

# print version to stdout
print(version)
