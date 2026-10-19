#!/usr/bin/env python3
"""Download and verify release assets using only Python's standard library."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
import tarfile
import tempfile
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "releases.json"
DEFAULT_DOWNLOADS = ROOT / "data" / "downloads"
DEFAULT_EXTRACTED = ROOT / "data" / "cleaned"
CHUNK_SIZE = 1024 * 1024


class DataToolError(Exception):
    """A manifest, integrity, download, or extraction error."""


def _filename(value: object, context: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise DataToolError(f"{context}: expected a plain, portable filename")
    if value.endswith(".") or re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", value, re.I):
        raise DataToolError(f"{context}: nonportable filename")
    return value


def _size(value: object, context: str) -> int:
    if type(value) is not int or value <= 0:
        raise DataToolError(f"{context}: bytes must be a positive integer")
    return value


def _digest(value: object, context: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise DataToolError(f"{context}: sha256 must contain exactly 64 hexadecimal digits")
    return value.lower()


def _asset(record: object, context: str) -> dict:
    if not isinstance(record, dict):
        raise DataToolError(f"{context}: expected an object")
    result = dict(record)
    result["filename"] = _filename(record.get("filename"), context)
    result["bytes"] = _size(record.get("bytes"), context)
    result["sha256"] = _digest(record.get("sha256"), context)
    url = record.get("url")
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise DataToolError(f"{context}: expected an HTTP(S) URL")
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise DataToolError(f"{context}: malformed URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise DataToolError(f"{context}: expected an HTTP(S) URL without credentials")
    return result


def load_manifest(path: Path | str = DEFAULT_MANIFEST) -> dict:
    """Strictly validate integrity metadata before any network or file mutation."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (OSError, ValueError) as exc:
        raise DataToolError(f"Cannot read manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise DataToolError("Manifest must be a JSON object")
    tag = manifest.get("release_tag")
    repo = manifest.get("repository")
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise DataToolError("release_tag must be a plain release identifier")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise DataToolError("repository must have the form owner/repository")
    raw = manifest.get("raw")
    if not isinstance(raw, dict):
        raise DataToolError("raw must be an object")
    raw = dict(raw)
    raw["filename"] = _filename(raw.get("filename"), "raw")
    raw["bytes"] = _size(raw.get("bytes"), "raw")
    raw["sha256"] = _digest(raw.get("sha256"), "raw")
    if not isinstance(raw.get("parts"), list) or not raw["parts"]:
        raise DataToolError("raw.parts must be a nonempty ordered list")
    raw["parts"] = [_asset(p, f"raw.parts[{i}]") for i, p in enumerate(raw["parts"])]
    if sum(p["bytes"] for p in raw["parts"]) != raw["bytes"]:
        raise DataToolError("Sum of raw part sizes does not match raw.bytes")
    cleaned = manifest.get("cleaned")
    if not isinstance(cleaned, list) or not cleaned:
        raise DataToolError("cleaned must be a nonempty list")
    cleaned = [_asset(p, f"cleaned[{i}]") for i, p in enumerate(cleaned)]
    cities: set[str] = set()
    names = {raw["filename"].casefold()}
    for record in raw["parts"] + cleaned:
        name = record["filename"].casefold()
        if name in names:
            raise DataToolError(f"Duplicate asset filename: {record['filename']}")
        names.add(name)
    for record in cleaned:
        city = record.get("city")
        if not isinstance(city, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", city):
            raise DataToolError("Every cleaned asset needs a lowercase city identifier")
        if city in cities:
            raise DataToolError(f"Duplicate cleaned city: {city}")
        if not record["filename"].endswith(".tar.gz"):
            raise DataToolError("Cleaned asset filenames must end with .tar.gz")
        cities.add(city)
    return {**manifest, "raw": raw, "cleaned": cleaned}


def select_cleaned(manifest: dict, cities: list[str] | None) -> list[dict]:
    requested = set(cities or [])
    known = {asset["city"] for asset in manifest["cleaned"]}
    if requested - known:
        raise DataToolError(f"Unknown city: {', '.join(sorted(requested - known))}; choose from {', '.join(sorted(known))}")
    return [a for a in manifest["cleaned"] if not requested or a["city"] in requested]


def asset_path(directory: Path, filename: str) -> Path:
    _filename(filename, "asset path")
    path = directory / filename
    if path.is_symlink():
        raise DataToolError(f"Refusing a symbolic-link output file: {path}")
    if path.exists() and not path.is_file():
        raise DataToolError(f"Expected a regular file: {path}")
    return path


def sha256_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_bytes: int, expected_sha256: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise DataToolError(f"Missing regular file (or symbolic link refused): {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_bytes:
        raise DataToolError(f"{path.name}: size mismatch: expected {expected_bytes}, found {actual_size}")
    actual = sha256_file(path)
    if actual != expected_sha256.lower():
        raise DataToolError(f"{path.name}: SHA256 mismatch: expected {expected_sha256.lower()}, found {actual}")
    return actual


def _content_range(response, offset: int, expected_size: int) -> None:
    header = response.headers.get("Content-Range", "")
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", header)
    if not match:
        raise DataToolError("206 response is missing a valid Content-Range")
    start, end, total = map(int, match.groups())
    if start != offset or end < start or end >= total or total != expected_size:
        raise DataToolError(f"Unexpected Content-Range: {header}")
    length = response.headers.get("Content-Length")
    if length is not None and int(length) != end - start + 1:
        raise DataToolError("Content-Length disagrees with Content-Range")


def download_asset(
    asset: dict,
    directory: Path,
    *,
    attempts: int = 3,
    timeout: float = 60,
    retry_delay: float = 1,
    chunk_size: int = CHUNK_SIZE,
    report: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> Path:
    """Resume only a verified 206 range; an ignored Range always restarts safely."""
    if attempts < 1:
        raise DataToolError("Download attempts must be at least 1")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    final = asset_path(directory, asset["filename"])
    partial = asset_path(directory, asset["filename"] + ".partial")
    if final.exists():
        try:
            verify_file(final, asset["bytes"], asset["sha256"])
            report(f"Verified existing {final.name}")
            return final
        except DataToolError:
            report(f"Existing {final.name} failed verification; replacing only after a valid download")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset >= asset["bytes"]:
                try:
                    verify_file(partial, asset["bytes"], asset["sha256"])
                except DataToolError:
                    partial.unlink()
                    offset = 0
                else:
                    os.replace(partial, final)
                    return final
            headers = {"User-Agent": "EVChargingDataDownloader/1.0", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            report(f"Fetching {asset['filename']} ({offset}/{asset['bytes']} bytes already saved)")
            request = urllib.request.Request(asset["url"], headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
                if status == 206:
                    _content_range(response, offset, asset["bytes"])
                    mode = "ab" if offset else "wb"
                elif status == 200:
                    # Servers may ignore Range. Never append a complete response.
                    mode = "wb"
                    offset = 0
                else:
                    raise DataToolError(f"Unexpected HTTP status {status}")
                length = response.headers.get("Content-Length")
                if length is not None and (int(length) < 0 or int(length) > asset["bytes"] - offset):
                    raise DataToolError("HTTP body size exceeds the manifest size")
                written = offset
                with partial.open(mode) as stream:
                    while chunk := response.read(chunk_size):
                        if written + len(chunk) > asset["bytes"]:
                            raise DataToolError("Downloaded content exceeds the manifest size")
                        stream.write(chunk)
                        written += len(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
            if partial.stat().st_size != asset["bytes"]:
                raise DataToolError(f"Incomplete {asset['filename']}: {partial.stat().st_size}/{asset['bytes']} bytes")
            actual = sha256_file(partial)
            if actual != asset["sha256"]:
                partial.unlink()
                raise DataToolError(f"{asset['filename']}: SHA256 mismatch; discarded partial download")
            os.replace(partial, final)
            report(f"Downloaded and verified {final.name}")
            return final
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException, DataToolError) as exc:
            last_error = exc
            report(f"{asset['filename']}: attempt {attempt + 1}/{attempts} failed: {exc}")
            if attempt + 1 < attempts and retry_delay:
                time.sleep(min(retry_delay * (2 ** attempt), 5))
    raise DataToolError(f"Could not download {asset['filename']}: {last_error}") from last_error


def reassemble_raw(raw: dict, directory: Path, chunk_size: int = CHUNK_SIZE) -> Path:
    """Verify all chunks, then atomically publish the verified concatenated ZIP."""
    directory = Path(directory)
    final = asset_path(directory, raw["filename"])
    if final.exists():
        try:
            verify_file(final, raw["bytes"], raw["sha256"])
            return final
        except DataToolError:
            pass
    parts = []
    for part in raw["parts"]:
        path = asset_path(directory, part["filename"])
        verify_file(path, part["bytes"], part["sha256"])
        parts.append(path)
    temporary = asset_path(directory, raw["filename"] + ".assembling")
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as output:
            for path in parts:
                with path.open("rb") as source:
                    while chunk := source.read(chunk_size):
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != raw["bytes"] or digest.hexdigest() != raw["sha256"]:
            raise DataToolError("Reassembled raw archive failed size/SHA256 verification")
        os.replace(temporary, final)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return final


def _tar_relative(name: str) -> Path:
    if not name or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise DataToolError(f"Unsafe tar member name: {name!r}")
    if PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive:
        raise DataToolError(f"Absolute tar path refused: {name!r}")
    parts = []
    for part in name.split("/"):
        if part in {"", "."}:
            continue
        if part == ".." or ":" in part or part.endswith((" ", ".")):
            raise DataToolError(f"Unsafe tar path component: {name!r}")
        if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", part, re.I):
            raise DataToolError(f"Nonportable tar member name: {name!r}")
        parts.append(part)
    return Path(*parts)


def safe_extract_tar(archive: Path, destination: Path) -> Path:
    """Extract regular files/directories into a staging directory, never links."""
    destination = Path(destination)
    if destination.is_symlink():
        raise DataToolError(f"Symbolic-link extraction directory refused: {destination}")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise DataToolError(f"Extraction destination must be absent or empty: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.extract-", dir=destination.parent))
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            validated = []
            seen: dict[str, bool] = {}
            for member in members:
                if not (member.isdir() or member.isreg()) or member.size < 0:
                    raise DataToolError(f"Tar links, devices and other special entries are refused: {member.name!r}")
                relative = _tar_relative(member.name)
                if relative == Path("."):
                    if not member.isdir():
                        raise DataToolError("A tar root entry must be a directory")
                    continue
                key = relative.as_posix().casefold()
                if key in seen:
                    raise DataToolError(f"Duplicate tar path refused: {member.name!r}")
                seen[key] = member.isdir()
                validated.append((member, relative))
            for _, relative in validated:
                for parent in relative.parents:
                    if parent != Path(".") and seen.get(parent.as_posix().casefold()) is False:
                        raise DataToolError(f"Tar file used as a parent directory: {relative}")
            for member, relative in validated:
                target = staging / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    if source is None:
                        raise DataToolError(f"Cannot read tar member: {member.name}")
                    with source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, CHUNK_SIZE)
                    if target.stat().st_size != member.size:
                        raise DataToolError(f"Incomplete tar member: {member.name}")
        if destination.exists():
            destination.rmdir()  # Only an empty destination was accepted.
        os.replace(staging, destination)
        return destination
    except (OSError, tarfile.TarError) as exc:
        raise DataToolError(f"Extraction failed: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    result.add_argument("--directory", type=Path, default=DEFAULT_DOWNLOADS, help="Download directory")
    result.add_argument("--kind", choices=("cleaned", "raw"), default="cleaned")
    result.add_argument("--city", action="extend", nargs="+", help="Cleaned city identifier(s); may be repeated")
    result.add_argument("--attempts", type=int, default=3, help="Attempts per asset, including the initial attempt")
    result.add_argument("--timeout", type=float, default=60, help="HTTP read timeout in seconds")
    result.add_argument("--extract", action="store_true", help="Safely extract cleaned tar assets after verification")
    result.add_argument("--extract-directory", type=Path, default=DEFAULT_EXTRACTED, help="City subdirectories are created here")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.attempts < 1 or args.timeout <= 0:
            raise DataToolError("--attempts and --timeout must be positive")
        if args.kind == "raw":
            if args.city or args.extract:
                raise DataToolError("--city and --extract apply only to --kind cleaned")
            for asset in manifest["raw"]["parts"]:
                download_asset(asset, args.directory, attempts=args.attempts, timeout=args.timeout)
            archive = reassemble_raw(manifest["raw"], args.directory)
            print(f"Verified raw archive: {archive}")
        else:
            for asset in select_cleaned(manifest, args.city):
                archive = download_asset(asset, args.directory, attempts=args.attempts, timeout=args.timeout)
                if args.extract:
                    target = safe_extract_tar(archive, args.extract_directory / asset["city"])
                    print(f"Extracted: {target}")
    except (DataToolError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
