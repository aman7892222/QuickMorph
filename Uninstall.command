#!/bin/sh
# macOS: double-click to uninstall (or run  python3 install.py --uninstall  in Terminal).
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || echo /usr/bin/python3)
"$PY" install.py --uninstall "$@"
echo; echo "Press Return to close this window."; read -r _
