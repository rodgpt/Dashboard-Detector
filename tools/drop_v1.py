"""Remove the v1 compatibility layer, in one go.

    make drop-v1

Deletes `api/app/services/legacy_v1.py` and its tests, and strips every block
marked LEGACY-V1-BEGIN .. LEGACY-V1-END. Nothing else in the codebase knows v1
existed, so what remains is the v2 path exactly as it would have been written
if v1 had never been read.

Run it when the production units are writing v2. Then: make test.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^[ \t]*# LEGACY-V1-BEGIN\b.*?^[ \t]*# LEGACY-V1-END\b[^\n]*\n",
                   re.DOTALL | re.MULTILINE)
FILES = ["api/app/services/legacy_v1.py", "api/tests/test_legacy_v1.py",
         "tools/drop_v1.py"]          # this script goes last, and goes too


def main() -> int:
    removed_blocks = 0
    for path in sorted(ROOT.rglob("*.py")):
        if not path.is_file() or "legacy_v1" in path.name:
            continue
        text = path.read_text()
        stripped, n = BLOCK.subn("", text)
        if n:
            path.write_text(stripped)
            removed_blocks += n
            print(f"  stripped {n} block(s)  {path.relative_to(ROOT)}")

    for rel in FILES:
        f = ROOT / rel
        if f.exists():
            f.unlink()
            print(f"  deleted              {rel}")

    leftovers = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
                 if p.is_file() and "LEGACY-V1" in p.read_text()]
    if leftovers:
        print("\nLEGACY-V1 still mentioned in: " + ", ".join(leftovers))
        return 1

    print(f"\n{removed_blocks} blocks removed, {len(FILES)} files deleted, nothing left behind.")
    print("Remove the drop-v1 target from the Makefile and OCEANKIND_V1_* from .env.")
    print("Set OCEANKIND_CONTRACT_VERSION=2 (or drop it, 2 is the default) and run: make test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
