#!/usr/bin/env bash

# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

set -euo pipefail

TARGET_PATH="latest-freecad.AppImage"

# dont do anything if current appimage is newer than five days
N_DAYS_AGO=/tmp/n-days-ago.$$
touch -d "5 days ago" $N_DAYS_AGO
if [[ -e "$TARGET_PATH" ]] && [[ "$TARGET_PATH" -nt "$N_DAYS_AGO" ]]; then
  echo 'AppImage is up to date, skipping download'
  exit 0
fi

REPO="FreeCAD/FreeCAD"
API_URL="https://api.github.com/repos/${REPO}/releases"

# ask for 15 latest releases 
RELEASES_JSON="$(curl -sSL "${API_URL}?per_page=15")"
if echo "${RELEASES_JSON}" | jq -e 'type == "object" and has("message")' >/dev/null 2>&1; then
  echo "github api request failed" >&2
  echo "${RELEASES_JSON}" | jq -r '.message' >&2
  exit 1
fi
 
# find x86_64 appimage (thanks claude!)
ASSET_INFO="$(echo "${RELEASES_JSON}" | jq -r '
    [.[] | .assets[] |
     select(.name | test("x86_64.*\\.AppImage$"; "i"))]
    | first
    | "\(.browser_download_url)\t\(.name)"' 2>/dev/null)"
DOWNLOAD_URL="$(echo "${ASSET_INFO}" | cut -f1)"
FILENAME="$(echo "${ASSET_INFO}" | cut -f2)"
 
echo "downloading ${FILENAME}" 
wget -nv --show-progress "${DOWNLOAD_URL}" -O "${TARGET_PATH}" 
chmod 755 "${TARGET_PATH}"
