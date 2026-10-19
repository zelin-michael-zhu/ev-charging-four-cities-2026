#!/usr/bin/env python3
"""Verify downloaded release assets locally; never make network requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from download_data import DEFAULT_DOWNLOADS, DEFAULT_MANIFEST, DataToolError, load_manifest, select_cleaned, verify_file


def verify_downloads(
    manifest: dict,
    directory: Path,
    *,
    kind: str = "all",
    cities: list[str] | None = None,
    require_all: bool = False,
) -> dict:
    records = []
    if kind in {"all", "cleaned"}:
        records.extend(select_cleaned(manifest, cities))
    elif cities:
        raise DataToolError("--city applies to cleaned assets")
    if kind in {"all", "raw"}:
        records.extend(manifest["raw"]["parts"])
        records.append(manifest["raw"])
    checked = []
    skipped = []
    errors = []
    for record in records:
        path = directory / record["filename"]
        required = require_all or bool(cities and record in manifest["cleaned"])
        if not path.exists() and not path.is_symlink():
            if required:
                errors.append({"filename": record["filename"], "error": "Missing file"})
            else:
                skipped.append(record["filename"])
            continue
        try:
            actual = verify_file(path, record["bytes"], record["sha256"])
            checked.append({"filename": record["filename"], "bytes": record["bytes"], "sha256": actual})
        except (DataToolError, OSError) as exc:
            errors.append({"filename": record["filename"], "error": str(exc)})
    return {"ok": not errors and bool(checked), "checked": checked, "skipped_missing": skipped, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DOWNLOADS)
    parser.add_argument("--kind", choices=("all", "raw", "cleaned"), default="all")
    parser.add_argument("--city", action="extend", nargs="+")
    parser.add_argument("--require-all", action="store_true", help="Require every selected asset, including raw parts AND the assembled ZIP")
    parser.add_argument("--manifest-only", action="store_true", help="Validate the manifest schema without opening data files")
    parser.add_argument("--json", action="store_true", help="Machine-readable verification report")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.manifest_only:
            report = {"ok": True, "manifest_only": True, "repository": manifest["repository"], "release_tag": manifest["release_tag"]}
        else:
            report = verify_downloads(manifest, args.directory, kind=args.kind, cities=args.city, require_all=args.require_all)
        if args.json:
            print(json.dumps(report, indent=2))
        elif args.manifest_only:
            print("Manifest schema and checksums are valid; no data files were checked.")
        else:
            for record in report["checked"]:
                print(f"OK {record['filename']} ({record['bytes']} bytes)")
            for record in report["errors"]:
                print(f"FAIL {record['filename']}: {record['error']}", file=sys.stderr)
            print(f"Checked {len(report['checked'])}; missing/skipped {len(report['skipped_missing'])}; errors {len(report['errors'])}")
            if not report["checked"]:
                print("No selected downloaded assets were found.", file=sys.stderr)
        return 0 if report["ok"] else 1
    except (DataToolError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
