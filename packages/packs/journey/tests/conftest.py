"""Make `packages/packs` importable when pytest is run from the repo root.

The container's PYTHONPATH will also include the packs directory once P3 lands the
`_example` pack; this keeps the pure tests runnable before that.
"""

import sys
from pathlib import Path

PACKS_ROOT = Path(__file__).resolve().parents[2]
if str(PACKS_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKS_ROOT))
