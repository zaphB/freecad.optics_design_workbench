#!/usr/bin/env bash

# change dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# clear dist folder and build freshly, create full copy of optics_design_workbench folder
# to make it available both via 'import freecad.optics_design_workbench' and
# 'import optics_design'. After building restore symlink.
rm -rf dist/* \
&& hatch build

# upload if enabled
if [[ "$1" == "--upload" ]]; then
  uvx uv-publish
fi
