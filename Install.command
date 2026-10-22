#!/bin/sh
# macOS: double-click to install (or run  python3 install.py  in Terminal).
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
        PY=$(command -v "$c"); break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.9+ was not found. Install it from https://www.python.org/downloads/macos/ (or: brew install python)."
else
    "$PY" install.py "$@"
fi
echo; echo "Press Return to close this window."; read -r _
