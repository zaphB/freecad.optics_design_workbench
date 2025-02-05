#!/usr/bin/env bash

# change parent dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# extract version info from setup.py
ver=$(./dev/update-packagexml.py)
major="$(echo "$ver" | grep -oP '^\d+')"
minor="$(echo "$ver" | grep -oP '\d+\.\d+$' | grep -oP '^\d+')"
micro="$(echo "$ver" | grep -oP '\d+$')"

# make new version number
newVer="$major.$(expr $minor + 1).0"

# replace version number in setup.py
echo && echo "-> version was $major.$minor.$micro, setting new version $newVer..." \
  && git tag "v$newVer" \
  && ./dev/update-packagexml.py \
  && git tag -d "v$newVer" \
  && echo && echo "-> adding all files and create new commit " \
  && git add . \
  && git commit $* \
  && git tag "v$newVer" \
  && echo "done."

