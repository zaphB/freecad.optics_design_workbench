#!/bin/bash

# cd this docker-test directory
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../test-docker"

for cnt in $(ls | grep -v broken); do

  echo "==================================================="
  echo "running tests in $cnt container..." 
  echo ""

  # cd to docker container folder
  cd $cnt

  # discard container home folder contents
  chmod 755 -R container-home 2>/dev/null
  rm -rf container-home/* 2>/dev/null

  # rebuild and start container
  docker compose down && docker compose up -d --build

  # make sure current version is copied to container-home
  mkdir -p ./container-home/.local/share/FreeCAD/Mod/exp_optics_workbench
  cp -r ../../freecad ./container-home/.local/share/FreeCAD/Mod/exp_optics_workbench
  cp -r ../../test ./container-home/

  # run unittests inside container
  docker exec --user testuser -it freecad-tumbleweed zsh -c "cd /home/testuser && python3 -m unittest --buffer --verbose" 
  #docker exec --user testuser -it freecad-tumbleweed bash -c "FreeCAD" 

  # shut down container
  docker compose down

  # cd back to parent folder
  cd ..

done
