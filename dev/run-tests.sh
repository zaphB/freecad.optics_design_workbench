#!/usr/bin/env bash

# getting options from command line
OPTS=""
ISDEFAULTOPTS=0
while [[ "$1" == -* ]]; do
  OPTS="$OPTS $1"
  shift
done
if [[ $OPTS == "" ]]; then
  OPTS='-v'
  ISDEFAULTOPTS=1
fi

# if anything left which is not opt, interpret as tests and replace default
TESTS="$*"
ISDEFAULTTESTS=0
if [[ "$TESTS" == "" ]]; then
  TESTS="test/**/*.py test/*.py"
  ISDEFAULTTESTS=1
fi

echo ""
echo -n "running with following options: $OPTS"
if [[ $ISDEFAULTOPTS == 1 ]]; then
  echo " (default)"
else
  echo ""
fi
echo -n "running the following tests: $TESTS"
if [[ $ISDEFAULTTESTS == 1 ]]; then
  echo " (default)"
else
  echo ""
fi
echo ""
if [[ $ISDEFAULTTESTS == 1 ]]; then
  echo "full test run selected, this will take many hours to complete"
  echo "starting in 30 seconds... (press ctrl+C to abort)"
  sleep 30
fi

# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# run cleanup only for full test run
if [[ $ISDEFAULTTESTS == 1 ]]; then
  echo 'running pre test cleanup...'
  ./dev/cleanup-test-folders.sh
  echo '=============================='
fi

# run unittests
uv run pytest $OPTS $TESTS || exit 1

# run cleanup only for full test run
if [[ $ISDEFAULTTESTS == 1 ]]; then
  echo '=============================='
  echo 'running post test cleanup...'
  ./dev/cleanup-test-folders.sh
  echo 'all done'
fi

# exit success
exit 0
