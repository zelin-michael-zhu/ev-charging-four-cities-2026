#!/usr/bin/env python3
"""Mirror only the four raw Figshare parts into an existing draft GitHub Release.

Run --dry-run to validate metadata and show the plan without network activity.
Real execution is restricted to the repository owner's main-branch Actions run.
Only empty starter assets positively identified as this run's own failed upload
may be deleted. No existing uploaded asset or release is replaced or published.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid

from download_data import DEFAULT_MANIFEST, DataToolError, load_manifest, verify_file


REPOSITORY = "zelin-michael-zhu/ev-charging-four-cities-2026"
UPSTREAM = "https://ndownloader.figshare.com/files/66387119"
DEFAULT_RELEASE_ID = 417197458
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
BLOCK_SIZE = 1024 * 1024
RESERVE_BYTES = 500_000_000
MAX_PLAN_BYTES = 14_000_000_000
RETRYABLE = {408, 429, 500, 502, 503, 504}


class MirrorError(Exception):
    pass


def load_plan(path: Path, release_id: int) -> dict:
    manifest = load_manifest(path)
    if manifest["repository"] != REPOSITORY:
        raise MirrorError("Manifest repository is not the authorized mirror repository")
    raw = manifest["raw"]
    if raw.get("upstream_download_url") != UPSTREAM:
        raise MirrorError("Manifest upstream URL is not the pinned official Figshare file")
    if release_id <= 0:
        raise MirrorError("release_id must be a positive integer")
    expected_names = [f"data.zip.part{i:02d}" for i in range(1, 5)]
    if raw["filename"] != "data.zip" or [p["filename"] for p in raw["parts"]] != expected_names:
        raise MirrorError("Expected exactly the four ordered data.zip.part01–part04 assets")
    # Raw archive + one local part + optional remote verification copy + reserve.
    peak = raw["bytes"] + 2 * max(p["bytes"] for p in raw["parts"]) + RESERVE_BYTES
    if peak >= MAX_PLAN_BYTES:
        raise MirrorError("Conservative temporary-space estimate reaches the 14 GB limit")
    return {
        "repository": REPOSITORY,
        "release_id": release_id,
        "release_tag": manifest["release_tag"],
        "raw": raw,
        "temporary_space_required_bytes": peak,
        "network_in_dry_run": False,
        "publishes_release": False,
        "uploads": [p["filename"] for p in raw["parts"]],
    }


def require_owner_actions() -> Path:
    owner = REPOSITORY.split("/", 1)[0]
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise MirrorError("Real mirroring is permitted only from GitHub Actions")
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise MirrorError("Real mirroring requires a manual workflow_dispatch event")
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise MirrorError("Workflow repository does not match the authorized repository")
    if os.environ.get("GITHUB_ACTOR", "").casefold() != owner.casefold():
        raise MirrorError("Only the repository owner may run this mirror")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise MirrorError("Real mirroring must run on refs/heads/main")
    runner_temp = os.environ.get("RUNNER_TEMP")
    if not runner_temp or not Path(runner_temp).is_dir():
        raise MirrorError("RUNNER_TEMP must identify an existing runner temporary directory")
    return Path(runner_temp)


def _quote(value: str) -> str:
    """Quote a curl config value, preventing config-line injection."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise MirrorError("Control characters are forbidden in curl config values")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def curl_transfer(
    url: str,
    output: Path,
    scratch: Path,
    *,
    token: str | None = None,
    method: str = "GET",
    upload_file: Path | None = None,
    accept: str = "application/vnd.github+json",
    max_time: int = 180,
    follow_redirects: bool = False,
) -> dict:
    """Stream curl output to disk; authentication exists only in config stdin."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise MirrorError("Only HTTPS URLs without credentials are allowed")
    if token and parsed.hostname not in {"api.github.com", "uploads.github.com"}:
        raise MirrorError("Authentication may only be sent to GitHub API/upload hosts")
    if token and follow_redirects:
        raise MirrorError("Authenticated redirects must be followed explicitly without the token")
    if method not in {"GET", "POST", "DELETE"}:
        raise MirrorError("Unexpected HTTP method")
    headers_path = scratch / ("headers-" + uuid.uuid4().hex)
    config = [
        "silent", "show-error", "http1.1",
        'proto = "=https"', 'proto-redir = "=https"',
        "connect-timeout = 45", f"max-time = {max_time}",
        "url = " + _quote(url),
        "request = " + _quote(method),
        "output = " + _quote(str(output)),
        "dump-header = " + _quote(str(headers_path)),
        'write-out = "%{http_code}"',
        'user-agent = "ev-charging-source-mirror/1.0"',
        "header = " + _quote("Accept: " + accept),
    ]
    if follow_redirects:
        config.append("location")
    if token:
        config.extend([
            "header = " + _quote("Authorization: Bearer " + token),
            'header = "X-GitHub-Api-Version: 2022-11-28"',
        ])
    if upload_file is not None:
        # --upload-file with explicit POST streams the file; --data-binary @file
        # can buffer the entire multi-gigabyte request in memory.
        config.extend([
            "upload-file = " + _quote(str(upload_file)),
            'header = "Content-Type: application/octet-stream"',
            "header = " + _quote("Content-Length: " + str(upload_file.stat().st_size)),
        ])
    child_env = {k: v for k, v in os.environ.items() if k not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    try:
        process = subprocess.run(
            ["curl", "--config", "-"],
            input=("\n".join(config) + "\n").encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=child_env, timeout=max_time + 60, check=False,
        )
        status_text = process.stdout.decode("ascii", errors="replace").strip()
        status = int(status_text) if status_text.isdigit() else 0
        header_text = headers_path.read_text(encoding="iso-8859-1") if headers_path.exists() else ""
        headers = {}
        for line in header_text.splitlines():
            if line.startswith("HTTP/"):
                headers = {}
            elif ":" in line:
                name, value = line.split(":", 1)
                headers[name.lower().strip()] = value.strip()
        error = process.stderr.decode(errors="replace")
        if token:
            error = error.replace(token, "<redacted>")
        return {"status": status, "returncode": process.returncode, "headers": headers, "error": error[-1500:]}
    except subprocess.TimeoutExpired as exc:
        raise MirrorError("curl exceeded its bounded transfer timeout") from exc
    finally:
        headers_path.unlink(missing_ok=True)


def retry_pause(result: dict, attempt: int) -> None:
    headers = result.get("headers", {})
    delay = min(5 * (2 ** attempt), 60)
    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            parsed = email.utils.parsedate_to_datetime(retry_after)
            delay = max(delay, parsed.timestamp() - time.time())
    elif headers.get("x-ratelimit-remaining") == "0":
        try:
            delay = max(delay, float(headers["x-ratelimit-reset"]) - time.time() + 1)
        except (KeyError, ValueError):
            delay = max(delay, 60)
    elif result.get("status") == 403:
        delay = max(delay, 60)
    if delay > 300:
        raise MirrorError("GitHub requested a retry wait over five minutes; rerun later")
    time.sleep(max(0, delay))


def is_retryable(result: dict) -> bool:
    return (
        result.get("returncode", 0) != 0
        or result.get("status", 0) in RETRYABLE
        or (
            result.get("status") == 403
            and (
                "retry-after" in result.get("headers", {})
                or result.get("headers", {}).get("x-ratelimit-remaining") == "0"
            )
        )
    )


class GitHub:
    def __init__(self, token: str, scratch: Path, plan: dict):
        self.token = token
        self.scratch = scratch
        self.plan = plan
        self.prefix = f"/repos/{REPOSITORY}"
        self.initial_asset_ids: set[int] = set()
        self.label = "source-mirror-" + os.environ.get("GITHUB_RUN_ID", "run") + "-" + uuid.uuid4().hex

    def json_request(self, path: str, *, method: str = "GET", accepted=(200,)) -> object:
        if not path.startswith(self.prefix + "/"):
            raise MirrorError("API path is outside the authorized repository")
        body_path = self.scratch / ("api-" + uuid.uuid4().hex + ".json")
        try:
            for attempt in range(5):
                body_path.unlink(missing_ok=True)
                result = curl_transfer(API + path, body_path, self.scratch, token=self.token, method=method)
                if result["returncode"] == 0 and result["status"] in accepted:
                    if result["status"] in {204, 404}:
                        return None
                    if body_path.stat().st_size > 8 * 1024 * 1024:
                        raise MirrorError("Unexpectedly large API JSON response")
                    try:
                        return json.loads(body_path.read_text())
                    except (OSError, ValueError) as exc:
                        if attempt == 4:
                            raise MirrorError("GitHub returned invalid JSON") from exc
                        retry_pause(result, attempt)
                        continue
                if not is_retryable(result) or attempt == 4:
                    raise MirrorError(f"GitHub {method} failed with HTTP {result['status']}: {result['error']}")
                retry_pause(result, attempt)
        finally:
            body_path.unlink(missing_ok=True)
        raise MirrorError("API retry limit exhausted")

    def release(self) -> dict:
        release_id = self.plan["release_id"]
        result = self.json_request(f"{self.prefix}/releases/{release_id}")
        if not isinstance(result, dict) or result.get("id") != release_id:
            raise MirrorError("GitHub did not return the exact requested release ID")
        if result.get("tag_name") != self.plan["release_tag"] or result.get("draft") is not True:
            raise MirrorError("Target release must have the manifest tag and remain draft")
        expected = f"{UPLOADS}{self.prefix}/releases/{release_id}/assets"
        if result.get("upload_url", "").split("{", 1)[0] != expected:
            raise MirrorError("Release upload URL does not match the authorized repository")
        return result

    def assets(self) -> list[dict]:
        result = []
        for page in range(1, 101):
            items = self.json_request(f"{self.prefix}/releases/{self.plan['release_id']}/assets?per_page=100&page={page}")
            if not isinstance(items, list):
                raise MirrorError("Expected a release asset list")
            result.extend(items)
            if len(items) < 100:
                return result
        raise MirrorError("Unexpectedly many release assets")

    def named_asset(self, name: str) -> dict | None:
        matches = [a for a in self.assets() if a.get("name") == name]
        if len(matches) > 1:
            raise MirrorError(f"Duplicate remote asset name: {name}")
        return matches[0] if matches else None

    def verify_remote(self, asset: dict, part: dict) -> None:
        if asset.get("state") != "uploaded" or asset.get("size") != part["bytes"]:
            raise MirrorError(f"Existing asset {part['filename']} has the wrong state or size; will not overwrite")
        digest = asset.get("digest")
        if digest is not None:
            if digest != "sha256:" + part["sha256"]:
                raise MirrorError(f"Existing asset {part['filename']} has the wrong digest; will not overwrite")
            return
        # Older assets may not expose digest metadata. Verify a streamed copy.
        asset_id = asset.get("id")
        if type(asset_id) is not int or asset_id <= 0:
            raise MirrorError("Invalid existing asset ID")
        temporary = self.scratch / "remote-verification.bin"
        try:
            for attempt in range(4):
                temporary.unlink(missing_ok=True)
                result = curl_transfer(
                    f"{API}{self.prefix}/releases/assets/{asset_id}",
                    temporary, self.scratch, token=self.token,
                    accept="application/octet-stream", max_time=2400,
                )
                if result["returncode"] == 0 and result["status"] == 302:
                    location = result["headers"].get("location", "")
                    parsed = urllib.parse.urlsplit(location)
                    if (
                        parsed.scheme != "https"
                        or not parsed.hostname
                        or not parsed.hostname.endswith(".githubusercontent.com")
                        or parsed.username
                        or parsed.password
                    ):
                        raise MirrorError("Unexpected GitHub release-asset redirect host")
                    # Deliberately do not pass GH_TOKEN to the storage host.
                    result = curl_transfer(
                        location, temporary, self.scratch,
                        accept="application/octet-stream", max_time=2400, follow_redirects=True,
                    )
                if result["returncode"] == 0 and result["status"] == 200:
                    verify_file(temporary, part["bytes"], part["sha256"])
                    return
                if not is_retryable(result) or attempt == 3:
                    raise MirrorError(f"Cannot verify existing remote asset: HTTP {result['status']}")
                retry_pause(result, attempt)
        finally:
            temporary.unlink(missing_ok=True)

    def remove_own_empty_starter(self, asset: dict) -> None:
        asset_id = asset.get("id")
        if (
            type(asset_id) is not int
            or asset_id <= 0
            or asset_id in self.initial_asset_ids
            or asset.get("state") != "starter"
            or asset.get("size") != 0
            or asset.get("label") != self.label
        ):
            raise MirrorError("Refusing to remove an asset not proven to be this run's new empty starter")
        self.release()
        fresh = self.json_request(f"{self.prefix}/releases/assets/{asset_id}")
        if (
            not isinstance(fresh, dict)
            or fresh.get("id") != asset_id
            or asset_id in self.initial_asset_ids
            or fresh.get("name") != asset.get("name")
            or fresh.get("state") != "starter"
            or fresh.get("size") != 0
            or fresh.get("label") != self.label
        ):
            raise MirrorError("Asset changed before cleanup; refusing to delete it")
        self.json_request(f"{self.prefix}/releases/assets/{asset_id}", method="DELETE", accepted=(204, 404))

    def upload(self, file: Path, part: dict) -> None:
        verify_file(file, part["bytes"], part["sha256"])
        response_path = self.scratch / "upload-response.json"
        last_result = {"status": 0, "returncode": 0, "headers": {}, "error": ""}
        attempted = False
        try:
            for attempt in range(5):
                self.release()
                existing = self.named_asset(part["filename"])
                if existing:
                    if existing.get("state") == "uploaded":
                        self.verify_remote(existing, part)
                        print(f"Verified remote asset; skip: {part['filename']}", flush=True)
                        return
                    if not attempted:
                        raise MirrorError(f"Pre-existing incomplete asset blocks upload: {part['filename']}")
                    self.remove_own_empty_starter(existing)
                if attempt:
                    retry_pause(last_result, attempt - 1)
                query = urllib.parse.urlencode({"name": part["filename"], "label": self.label})
                upload_url = f"{UPLOADS}{self.prefix}/releases/{self.plan['release_id']}/assets?{query}"
                print(f"Uploading {part['filename']} (attempt {attempt + 1}/5)", flush=True)
                attempted = True
                response_path.unlink(missing_ok=True)
                last_result = curl_transfer(
                    upload_url, response_path, self.scratch, token=self.token,
                    method="POST", upload_file=file, max_time=2400,
                )
                if last_result["returncode"] == 0 and last_result["status"] == 201:
                    try:
                        asset = json.loads(response_path.read_text())
                    except (OSError, ValueError):
                        continue  # Resolve ambiguous completion via the asset API.
                    if asset.get("name") != part["filename"]:
                        raise MirrorError("Uploaded asset name does not match the requested part")
                    self.verify_remote(asset, part)
                    print(f"Uploaded and verified: {part['filename']}", flush=True)
                    return
                # A 422 can mean an earlier ambiguous POST completed successfully.
                if not is_retryable(last_result) and last_result["status"] != 422:
                    raise MirrorError(f"Upload failed with HTTP {last_result['status']}: {last_result['error']}")
            existing = self.named_asset(part["filename"])
            if existing and existing.get("state") == "uploaded":
                self.verify_remote(existing, part)
                return
            raise MirrorError(f"Upload retry limit exhausted: {part['filename']}")
        finally:
            response_path.unlink(missing_ok=True)


def download_upstream(plan: dict, scratch: Path) -> Path:
    raw = plan["raw"]
    output = scratch / raw["filename"]
    for attempt in range(4):
        output.unlink(missing_ok=True)
        print(f"Downloading pinned official Figshare archive (attempt {attempt + 1}/4)", flush=True)
        result = curl_transfer(UPSTREAM, output, scratch, max_time=3600, follow_redirects=True)
        if result["returncode"] == 0 and result["status"] == 200:
            try:
                verify_file(output, raw["bytes"], raw["sha256"])
                print("Official archive size and SHA256 verified", flush=True)
                return output
            except DataToolError:
                output.unlink(missing_ok=True)
                if attempt == 3:
                    raise
        elif not is_retryable(result) or attempt == 3:
            raise MirrorError(f"Upstream download failed: HTTP {result['status']}: {result['error']}")
        retry_pause(result, attempt)
    raise MirrorError("Upstream verification retry limit exhausted")


def split_part(source, part: dict, destination: Path) -> None:
    remaining = part["bytes"]
    digest = hashlib.sha256()
    with destination.open("xb") as output:
        while remaining:
            block = source.read(min(BLOCK_SIZE, remaining))
            if not block:
                raise MirrorError("Original archive ended before the expected part boundary")
            output.write(block)
            digest.update(block)
            remaining -= len(block)
    if digest.hexdigest() != part["sha256"]:
        raise MirrorError(f"Split part SHA256 mismatch: {part['filename']}")
    verify_file(destination, part["bytes"], part["sha256"])


def mirror(plan: dict, token: str, runner_temp: Path) -> None:
    if shutil.which("curl") is None:
        raise MirrorError("curl is required")
    required = plan["temporary_space_required_bytes"]
    if shutil.disk_usage(runner_temp).free < required:
        raise MirrorError(f"Need at least {required} free bytes in RUNNER_TEMP")
    with tempfile.TemporaryDirectory(prefix="ev-source-mirror-", dir=runner_temp) as name:
        scratch = Path(name)
        github = GitHub(token, scratch, plan)
        github.release()
        initial = github.assets()
        github.initial_asset_ids = {a["id"] for a in initial if type(a.get("id")) is int}
        completed = set()
        for part in plan["raw"]["parts"]:
            matches = [a for a in initial if a.get("name") == part["filename"]]
            if len(matches) > 1:
                raise MirrorError("Duplicate remote raw asset names")
            if matches:
                github.verify_remote(matches[0], part)
                completed.add(part["filename"])
                print(f"Verified pre-existing asset; skip: {part['filename']}", flush=True)
        if len(completed) != len(plan["raw"]["parts"]):
            original = download_upstream(plan, scratch)
            with original.open("rb") as source:
                for part in plan["raw"]["parts"]:
                    local_part = scratch / part["filename"]
                    try:
                        # Verify every split, including parts already present remotely.
                        split_part(source, part, local_part)
                        if part["filename"] not in completed:
                            github.upload(local_part, part)
                    finally:
                        local_part.unlink(missing_ok=True)
                if source.read(1):
                    raise MirrorError("Unexpected bytes remain after the last manifest part")
        github.release()
        for part in plan["raw"]["parts"]:
            remote = github.named_asset(part["filename"])
            if not remote:
                raise MirrorError(f"Expected remote asset is missing: {part['filename']}")
            github.verify_remote(remote, part)
        print("All four raw assets verified. Release is still draft; nothing was published.", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--release-id", type=int, default=DEFAULT_RELEASE_ID)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the plan; no token or network required")
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.manifest, args.release_id)
        if args.dry_run:
            print(json.dumps(plan, indent=2))
            return 0
        runner_temp = require_owner_actions()
        token = os.environ.pop("GH_TOKEN", "")
        if not token:
            raise MirrorError("GH_TOKEN is required for the owner Actions run")
        mirror(plan, token, runner_temp)
    except (DataToolError, MirrorError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
