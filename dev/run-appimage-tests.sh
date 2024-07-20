#!/bin/bash

# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# make sure appimage is up to date
./dev/download-latest-appimage.sh

# run freecad based tests with app image instead of system freecad
export TEST_FREECAD_BINARY="$(realpath freecad-weekly-appimage.AppImage)"
python -m unittest --verbose --buffer
