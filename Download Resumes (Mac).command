#!/bin/bash
# Double-click this file to download every resume.
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "Python is not installed."
  echo "Install it from https://www.python.org/downloads/ then double-click this again."
  read -r -p "Press Enter to close..."
  exit 1
fi
"$PY" get_resumes.py
echo
read -r -p "Press Enter to close..."
