# change dir to parent dir of this script's location
cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# download appimage if not existing or old
N_DAYS_AGO=/tmp/n-days-ago.$$
touch -d "5 days ago" $N_DAYS_AGO
if [[ ! -e freecad-weekly-appimage.AppImage ]] || [[ "freecad-weekly-appimage.AppImage" -ot "$N_DAYS_AGO" ]]; then
  echo 'downloading latest freecad appimage...'
  DOWNLOAD_URL=$(curl https://api.github.com/repos/FreeCAD/FreeCAD-Bundle/releases | grep 'weekly.*conda-Linux-x86_64-py311.AppImage[^a-zA-Z\.0-9\-]' | head -2 | grep 'download' | grep -Po '"[^"]+"' | tail -1 | sed 's/\"//g')
  wget $DOWNLOAD_URL -O freecad-weekly-appimage.AppImage
  chmod 755 freecad-weekly-appimage.AppImage
fi
