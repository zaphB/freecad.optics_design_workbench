#!/usr/bin/env bash

# change dir to docs folder of this project
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../docs"

# update docs
if [[ "$1" == "dev" ]]; then
  uv run --dev sphinx-autobuild -E . _build/html --open-browser --watch=../freecad --ignore "*.tmp"
else
  uv run --dev sphinx-build -E -b html . _build/html
fi
