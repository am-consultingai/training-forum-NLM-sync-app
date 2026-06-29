"""Make both the repo root (for `import backend...`) and this tests dir (for
`import fake_drive`) importable regardless of where pytest is invoked from."""
import os
import sys

_HERE = os.path.dirname(__file__)
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
