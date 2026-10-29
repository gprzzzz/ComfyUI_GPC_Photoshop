#!/bin/sh
# Installs the GPC ComfyUI panel for Photoshop without Creative Cloud.
# It links this folder into your CEP extensions folder (so a git pull updates it)
# and allows unsigned extensions, which a self-built panel needs.
set -e

EXT="$HOME/Library/Application Support/Adobe/CEP/extensions"
TARGET="$EXT/com.gpc.comfyui.photoshop"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$HERE/CSXS/manifest.xml" ]; then
  echo "Run this from the photoshop folder of ComfyUI_GPC_Photoshop: CSXS/manifest.xml is missing here."
  exit 1
fi

mkdir -p "$EXT"
if [ -L "$TARGET" ]; then rm "$TARGET"; fi
if [ -e "$TARGET" ]; then
  echo "$TARGET exists and is not a link from an earlier install. Delete it, then run this again."
  exit 1
fi
ln -s "$HERE" "$TARGET"

# Photoshop versions read this setting for different CEP versions; set them all.
# LogLevel 6 writes CEP logs to ~/Library/Logs/CSXS, for when the panel doesn't load.
for v in 9 10 11 12; do
  defaults write "com.adobe.CSXS.$v" PlayerDebugMode 1
  defaults write "com.adobe.CSXS.$v" LogLevel 6
done
# macOS caches preferences; make sure Photoshop reads the new values.
killall cfprefsd 2>/dev/null || true

echo "Installed: $TARGET -> $HERE"
echo "Restart Photoshop, then open Window > Extensions (legacy) > GPC ComfyUI."
