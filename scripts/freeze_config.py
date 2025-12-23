import sys
from pathlib import Path

from ftmo_bot.config import freeze_config, verify_config_lock


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/freeze_config.py <config_path>")
    path = Path(sys.argv[1])
    lock_path = freeze_config(path)
    ok = verify_config_lock(path, lock_path)
    status = "ok" if ok else "mismatch"
    print(f"Frozen {path} -> {lock_path} ({status})")


if __name__ == "__main__":
    main()
