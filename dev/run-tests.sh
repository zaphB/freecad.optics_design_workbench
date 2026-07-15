#!/usr/bin/env bash

TESTS="$*"
if [[ "$TESTS" == "" ]]; then
  TESTS="test/**/*.py test/*.py"
fi
echo "running the following tests: $TESTS"
sleep 3

# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# run unittests
uv run pytest -v $TESTS || exit 1

# run cleanup
#echo 'running cleanup...'
#./dev/cleanup-test-folders.sh

# exit success
exit 0
