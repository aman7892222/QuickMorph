"""Launcher used by the right-click menu (Windows runs it with pythonw.exe -> no console window).

Lives next to the `quickmorph` package and a `libs` folder of third-party dependencies,
so the installed app is fully self-contained in its own folder.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "libs"), HERE):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

from quickmorph.cli import main  # noqa: E402

sys.exit(main())
