#!/bin/bash
# fn.sh <file> <selector-regex>  -> print that function's disassembly
awk -v pat="$2" '
/^===== /{ p = ($0 ~ pat) }
p { print }
' "dis/$1.txt"
