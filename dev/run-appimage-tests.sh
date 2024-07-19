#!/bin/bash

# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# download appimage if not existing or old
N_DAYS_AGO=/tmp/n-days-ago.$$
touch -d "5 days ago" $N_DAYS_AGO
if [[ ! -e freecad-weekly-appimage.AppImage ]] || [[ "freecad-weekly-appimage.AppImage" -ot "$N_DAYS_AGO" ]]; then
  echo 'downloading latest freecad appimage...'
  DOWNLOAD_URL=$(curl https://api.github.com/repos/FreeCAD/FreeCAD-Bundle/releases | grep 'weekly.*conda-Linux-x86_64-py311.AppImage' | head -2 | grep 'download' | grep -Po '"[^"]+"' | tail -1)
  wget $DOWNLOAD_URL -O freecad-weekly-appimage.AppImage
  chmod 755 freecad-weekly-appimage.AppImage
fi

# run freecad based tests with app image instead of system freecad
export TEST_FREECAD_BINARY="$(realpath freecad-weekly-appimage.AppImage)"
python -m unittest --verbose --buffer
