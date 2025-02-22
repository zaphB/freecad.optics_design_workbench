#!/usr/bin/env bash

# change dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# clear dist folder and build freshly, create full copy of optics_design_workbench folder
# to make it available both via 'import freecad.optics_design_workbench' and
# 'import optics_design_workbench'. After building restore symlink.
rm -rf dist \
&& rm -rf optics_design_workbench \
&& cp -r freecad/optics_design_workbench . \
&& hatch build

# upload if enabled
if [[ "$1" == "--upload" ]]; then
  uvx uv-publish
fi
