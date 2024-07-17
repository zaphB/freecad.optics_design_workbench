#!/usr/bin/env bash

# change parent dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# error and exit if setup.py not found
if [ ! -e setup.py ]; then
  echo "could not find setup.py"
  exit 1
fi

# extract version info from setup.py
ver=$(./dev/update-setup.py --clean)
major="$(echo "$ver" | grep -oP '^\d+')"
minor="$(echo "$ver" | grep -oP '\d+\.\d+$' | grep -oP '^\d+')"
micro="$(echo "$ver" | grep -oP '\d+$')"

# make new version number
newVer="$major.$minor.$(expr $micro + 1)"

# replace version number in setup.py
echo && echo "-> version was $major.$minor.$micro, setting new version $newVer..." \
  && echo "__version__ = '$newVer'" > freecad/optics_design_workbench/version.py \
  && echo "done." \
  && pip install . \
  && pip install -e . \
  && echo && echo "-> adding all files and create new commit " \
  && git add . \
  && git commit $* \
  && git tag "v$newVer" \
  && echo "done."
