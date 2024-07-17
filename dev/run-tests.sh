#!/usr/bin/env bash

# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# install package
pip install -e .

# run unittests
python -m unittest --verbose --buffer || exit 1

# exit success
exit 0
