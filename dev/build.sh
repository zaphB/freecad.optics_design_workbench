#!/usr/bin/env bash

# change dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# This removes the freecad-link before building and uploading to PyPi, to prevent building as a namespace
# package. It has to be done this way, because using include/exclude options in pyproject.toml did not make
# hatch ingore the freecad symlink (not sure if this is a bug or intentional).
# The package uploaded to PyPi has to be expose a non-namespace 'optics_design_workbench' package, because
# the freecad namespace base package is not pip-installable (e.g. to virtual environments). Running 
# "import freecad.optics_design_workbench" will therefore fail with "module freecad not found" in virtual 
# environments.
# For FreeCADs add-on manager, which downloads from the github repo, this project will look like a namespace
# package, because of the freecad -> src symlink.
# Hopefully the freecad base package will be added to PyPi in the future, to remove necessity for this mess.
rm freecad \
&& rm -rf dist \
&& hatch build \

# restore link and remove src/optics_design_workbench copy
ln -s src freecad

# upload if enabled
if [[ "$1" == "--upload" ]]; then
  uvx uv-publish
fi
