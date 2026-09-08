import sys

# Windows' default console codepage (cp1252) can't encode many characters
# this pipeline prints/logs (checkmarks, box-drawing, currency symbols,
# arrows, emoji). Reconfiguring here - rather than in each entry-point
# script - covers every `python -m src.*` invocation and any module that
# imports from `src`, since Python always runs a package's __init__.py
# before its submodules.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
