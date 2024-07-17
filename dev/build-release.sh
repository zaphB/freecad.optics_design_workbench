#!/bin/bash

# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# get version identifier
ver=$('./dev/update-setup.py')

# create zip archive ready to be extracted to freecad's Mod folder
mkdir -p ./releases
tar -czf ./releases/ExpOpticsWorkbench-v$ver.tar.gz --transform 's/^\./exp_optics_workbench/' --exclude '__pycache__' ./freecad 
