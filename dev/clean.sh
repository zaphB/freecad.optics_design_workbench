#!/bin/bash

# change parent dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# remove build/test related folders
rm -rf ./build
rm -rf *.egg-info
rm -rf ./freecad-weekly-appimage.AppImage

rm -rf ./test-docker/**/container-home/*
rm -rf ./test/**/*.opticalSimulationResults
rm -rf ./test/**/*.FCBak
rm -rf ./fcstd/*.opticalSimulationResults
rm -rf ./fcstd/*.FCBak
rm -rf ./examples/*.opticalSimulationResults
rm -rf ./examples/*.FCBak
