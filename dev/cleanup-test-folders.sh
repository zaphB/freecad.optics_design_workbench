#!/bin/bash

# change parent dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# remove flag files from ungently quits
rm ./test/**/*.OpticsDesign/simulation-is-running

# remove raw and tmp folders containing ray tracing results
rm -rf ./test/**/*.OpticsDesign/__pycache__
rm -rf ./test/**/*.OpticsDesign/raw
rm -rf ./test/**/*.OpticsDesign/tmp

# remove all log files
rm -rf ./test/**/*.OpticsDesign/*.log

# remove all backup files created by FreeCAD
rm -rf ./test/**/*.FCBak

