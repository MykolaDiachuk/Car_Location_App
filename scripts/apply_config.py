"""Apply a parking_config.zip produced by parking_configurator.

Usage:
    python scripts/apply_config.py path/to/parking_config.zip

Merges the bundled .env into the project's .env (preserves comments and
unrelated keys; replaces matching keys; appends new ones) and writes the
mask PNGs / map SVG into ``assets/``. Prints a summary of what changed.

Safe to re-run — overwrites only the keys present in the bundle.
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ASSETS_DIR = PROJECT_ROOT / "assets"

ASSET_NAMES = {
    "assets/parking_mask.png",
    "assets/orientation_zones.png",
    "assets/parking_map.svg",
}

KEY_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines into a dict. Ignores comments and blanks."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip()
    return out


def merge_env(existing: str, incoming: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """Merge ``incoming`` into ``existing`` .env text.

    Replaces lines for keys present in both; appends keys only in
    ``incoming`` at the end. Preserves comments and ordering.
    Returns (new_text, replaced_keys, appended_keys).
    """
    lines = existing.splitlines(keepends=False)
    seen: set[str] = set()
    replaced: list[str] = []
    out_lines: list[str] = []

    for line in lines:
        match = KEY_LINE.match(line)
        if match:
            key = match.group(1)
            if key in incoming:
                out_lines.append(f"{key}={incoming[key]}")
                seen.add(key)
                replaced.append(key)
                continue
        out_lines.append(line)

    appended = [k for k in incoming if k not in seen]
    if appended:
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append("# Added by apply_config.py")
        for key in appended:
            out_lines.append(f"{key}={incoming[key]}")

    return "\n".join(out_lines) + "\n", replaced, appended


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply parking_config.zip produced by parking_configurator."
    )
    parser.add_argument("zip_path", type=Path, help="path to parking_config.zip")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change without writing anything",
    )
    args = parser.parse_args()

    if not args.zip_path.is_file():
        print(f"error: {args.zip_path} not found", file=sys.stderr)
        return 1

    try:
        zf = zipfile.ZipFile(args.zip_path)
    except zipfile.BadZipFile:
        print(f"error: {args.zip_path} is not a valid ZIP", file=sys.stderr)
        return 1

    names = set(zf.namelist())
    if ".env" not in names:
        print("error: ZIP is missing .env - was this produced by parking_configurator?", file=sys.stderr)
        return 1

    incoming_env_text = zf.read(".env").decode("utf-8")
    incoming = parse_env(incoming_env_text)
    if not incoming:
        print("error: bundled .env has no key=value pairs", file=sys.stderr)
        return 1

    if ENV_PATH.exists():
        existing = ENV_PATH.read_text(encoding="utf-8")
        new_text, replaced, appended = merge_env(existing, incoming)
    else:
        new_text = incoming_env_text
        replaced = []
        appended = list(incoming.keys())

    asset_writes: list[tuple[str, Path, int]] = []
    for name in sorted(names & ASSET_NAMES):
        data = zf.read(name)
        dest = PROJECT_ROOT / name
        asset_writes.append((name, dest, len(data)))

    # ── Report ────────────────────────────────────────────────────────────
    print(f"Source:      {args.zip_path}")
    print(f"Target .env: {ENV_PATH}")
    if replaced:
        print(f"  replaced keys: {', '.join(replaced)}")
    if appended:
        print(f"  appended keys: {', '.join(appended)}")
    if not replaced and not appended:
        print("  (no .env changes)")
    print(f"Assets dir:  {ASSETS_DIR}")
    if asset_writes:
        for name, dest, size in asset_writes:
            print(f"  write {name} -> {dest} ({size:,} bytes)")
    else:
        print("  (no asset files in bundle)")

    if args.dry_run:
        print("\nDry run - nothing written.")
        return 0

    ENV_PATH.write_text(new_text, encoding="utf-8")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for name, dest, _ in asset_writes:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(name) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)

    print("\nDone. Restart the app to pick up the new configuration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
