#!/usr/bin/env bash

# getting options from command line
OPTS=()
ISDEFAULTOPTS=0
while [[ "$1" == -* ]]; do
  if [[ "$1" == -*m ]]; then
    OPTS+=($1 "$2")
    shift 2
  else
    OPTS+=("$1")
    shift
  fi
done
if [[ ${#OPTS[@]} == 0 ]]; then
  OPTS=(--cov=freecad --junitxml=junit.xml)
  ISDEFAULTOPTS=1
fi

# if anything left which is not opt, interpret as tests and replace default
TESTS=()
ISDEFAULTTESTS=0
while [[ "$1" != "" ]]; do
  if [[ "$1" == *.py ]]; then
    TESTS+=("$1")
  else
    if [[ -e "$1.py" ]]; then
      TESTS+=("$1.py")
    else
      if [[ -e "$1" ]]; then
        expanded=$(ls "$1"/*.py)
        TESTS+=($expanded)
        expanded=$(ls "$1"/**/*.py)
        TESTS+=($expanded)
      else
	TESTS+=("$1")
      fi
    fi
  fi
  shift
done
if [[ "${#TESTS[@]}" == 0 ]]; then
  TESTS=(test/**/*.py test/*.py)
  ISDEFAULTTESTS=1
fi

if [[ $ISDEFAULTTESTS == 1 ]]; then
  echo ""
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

# debug prints
#printf '[%s]\n' "${OPTS[@]}"
#printf '[%s]\n' "${TESTS[@]}"

# run unittests
echo
echo -n "OPTIONS: "
for o in "${OPTS[@]}"; do
  if [[ "$o" == *" "* ]]; then
    printf '"%s" ' "$o"
  else
    printf '%s ' "$o"
  fi
done
echo
echo
echo -n "SELECTED TEST FILES: "
for o in "${TESTS[@]}"; do
  if [[ "$o" == *" "* ]]; then
    printf '"%s" ' "$o"
  else
    printf '%s ' "$o"
  fi
done
echo
echo

# make sure app image is up-to-date
./dev/download-latest-appimage.sh

# run actual tests
uv run pytest "${OPTS[@]}" "${TESTS[@]}"
exitCode=$?

# run coverage report updates only when all tests were run
# and only default options were used (e.g. no -m 'filter' was used)
if [[ $ISDEFAULTTESTS == 1 ]] && [[ $ISDEFAULTOPTS == 1 ]]; then
  echo "updating coverage html report and icon..."
  # make pass/fail badge
  uv run genbadge tests -i junit.xml -o badge-tests.svg
  # make coverage badge
  uv run coverage-badge -o badge-coverage.svg -f
  # make coverage html report
  uv run coverage html
fi

# run cleanup only for full test run and if successful
if [[ $exitCode == 0 ]] && [[ $ISDEFAULTTESTS == 1 ]]; then
  echo 
  echo '=============================='
  echo 'running post test cleanup...'
  ./dev/cleanup-test-folders.sh
  echo 'all done'
fi

# exit with returncode given by pytest
exit $exitCode
