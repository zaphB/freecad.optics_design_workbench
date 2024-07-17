#!/bin/bash

# change dir to this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")"

echo 'setting up git hooks'
git config core.hooksPath ./dev/hooks

echo setting up filter for jupyter notebooks...
git config filter.clean-ipynb.smudge ./dev/clean-ipynb.py
git config filter.clean-ipynb.clean  ./dev/clean-ipynb.py

echo done.

