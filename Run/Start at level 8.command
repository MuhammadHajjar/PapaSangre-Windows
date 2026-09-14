#!/bin/bash
# Mac equivalent of "Start at level 8.cmd" - double-clickable in Finder.
cd "$(dirname "$0")"
if [ ! -x "./Play Papa Sangre.app/Contents/MacOS/Play Papa Sangre" ]; then
    echo "The game is not built yet.  Run:  python tools/build_exes.py play"
    read -r -p "Press Enter to close." _
    exit 1
fi
exec "./Play Papa Sangre.app/Contents/MacOS/Play Papa Sangre" "ps1_8"
