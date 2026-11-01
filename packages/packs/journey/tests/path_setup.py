"""Make `packages/packs` importable when pytest is run from the repo root.

The container's PYTHONPATH will also include the packs directory once P3 lands the
`_example` pack; this keeps the pure tests runnable before that.
"""

import sys
from pathlib import Path

PACKAGES_ROOT = Path(__file__).resolve().parents[3]
if str(PACKAGES_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGES_ROOT))

# Renamed from conftest.py: it shadowed the root tests/conftest.py when pytest collected packages.
# The root pytest config already adds packages to pythonpath.
