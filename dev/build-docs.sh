#!/usr/bin/env bash

# change dir to docs folder of this project
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/../docs"

uv run --all-extras sphinx-build . _build/html
