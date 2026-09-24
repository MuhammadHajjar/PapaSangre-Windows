#!/bin/bash
# Mac equivalent of "Start at level 5.cmd" - double-clickable in Finder.
cd "$(dirname "$0")"
if [ ! -x "./Papa Sangre.app/Contents/MacOS/Papa Sangre" ]; then
    echo "The game is not built yet.  Run:  python tools/build_exes.py play"
    read -r -p "Press Enter to close." _
    exit 1
fi
exec "./Papa Sangre.app/Contents/MacOS/Papa Sangre" "ps1_5"
