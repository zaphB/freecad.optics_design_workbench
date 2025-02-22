#!/usr/bin/env bash

# change dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# clear dist folder and build freshly
rm -rf dist \
&& uv build

# upload if enabled
if [[ "$1" == "--upload" ]]; then
  uvx uv-publish
fi
