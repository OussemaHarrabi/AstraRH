"""Migration commands, run by the migrate service with the owner role.

    python -m kernel.migrate up
    python -m kernel.migrate new <kernel|pack> "message"

Each pack has its own Alembic branch, so teammates never hit conflicting heads.
"""

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
KERNEL_VERSIONS = ROOT / "packages/kernel/migrations/versions"
PACKS_DIR = ROOT / "packages/packs"


def pack_version_dirs() -> dict[str, Path]:
    if not PACKS_DIR.exists():
        return {}
    return {
        path.parent.parent.name: path for path in sorted(PACKS_DIR.glob("*/migrations/versions"))
    }


def config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "packages/kernel/migrations"))
    cfg.set_main_option("path_separator", "os")
    locations = [str(KERNEL_VERSIONS), *map(str, pack_version_dirs().values())]
    cfg.set_main_option("version_locations", os.pathsep.join(locations))
    return cfg


def upgrade() -> None:
    from kernel.registry import sync_catalogue

    command.upgrade(config(), "heads")
    sync_catalogue()


def new_revision(scope: str, message: str) -> None:
    cfg = config()
    version_path = KERNEL_VERSIONS if scope == "kernel" else pack_version_dirs().get(scope)
    if version_path is None:
        raise SystemExit(
            f"Unknown scope {scope!r}. Create packages/packs/{scope}/migrations first."
        )
    version_path.mkdir(parents=True, exist_ok=True)

    script = ScriptDirectory.from_config(cfg)
    branch_exists = any(scope in (rev.branch_labels or ()) for rev in script.walk_revisions())
    os.environ["ALEMBIC_SCOPE"] = scope
    options = (
        {"head": f"{scope}@head"} if branch_exists else {"head": "base", "branch_label": scope}
    )
    if not branch_exists and scope != "kernel":
        options["depends_on"] = "kernel@head"
    command.revision(
        cfg, message=message, autogenerate=True, version_path=str(version_path), **options
    )


def main() -> None:
    args = sys.argv[1:]
    if args == ["up"]:
        upgrade()
    elif len(args) == 3 and args[0] == "new":
        new_revision(args[1], args[2])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
