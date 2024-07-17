#!/bin/bash

# cd this docker-test directory
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../test-docker"

cnt='tumbleweed'
if [[ "$1" != "" ]]; then
  cnt="$1"
fi

# cd to docker container folder
cd $cnt || exit 1

# rebuild and start container
docker compose down && docker compose up -d --build

# make sure current version is copied to container-home
mkdir -p ./container-home/.local/share/FreeCAD/Mod/exp_optics_workbench
cp -r ../../freecad ./container-home/.local/share/FreeCAD/Mod/exp_optics_workbench
cp -r ../../test ./container-home/

# run unittests inside container
docker exec --user testuser -it freecad-tumbleweed zsh -c "FreeCAD" 

# shut down container
docker compose down
