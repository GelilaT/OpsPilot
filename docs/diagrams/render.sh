#!/bin/bash
# Renders every SVG in this folder to PNG (1.5x) using headless Chrome.
cd "$(dirname "$0")"
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for f in *.svg; do
  w=$(grep -o 'width="[0-9]*"' "$f" | head -1 | tr -dc 0-9)
  h=$(grep -o 'height="[0-9]*"' "$f" | head -1 | tr -dc 0-9)
  "$CH" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1.5 --window-size=$w,$h --screenshot="$PWD/${f%.svg}.png" "file://$PWD/$f" 2>/dev/null
done
