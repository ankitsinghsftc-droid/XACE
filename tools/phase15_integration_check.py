import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from certify_launch import main as certify_main  # noqa: E402


def main() -> int:
    return certify_main(["--target-dir", str(REPO_ROOT / "target-codex-phase15"), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
