"""Synthetic, offline/local-HTTP tests. No real release assets are requested."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import download_data as download
import verify_data as verify


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tar_bytes(entries):
    """Each entry is (name, payload, optional tar type)."""
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w:gz") as bundle:
        for name, data, kind in entries:
            member = tarfile.TarInfo(name)
            if kind is not None:
                member.type = kind
                if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                    member.linkname = "../outside"
            payload = data or b""
            member.size = len(payload) if member.isreg() else 0
            bundle.addfile(member, io.BytesIO(payload) if member.isreg() else None)
    return target.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        server = self.server
        server.calls.append((self.path, self.headers.get("Range")))
        if self.path not in server.payloads:
            self.send_error(404)
            return
        data = server.payloads[self.path]
        requested = self.headers.get("Range")
        if requested and self.path not in server.ignore_ranges:
            start = int(requested.removeprefix("bytes=").removesuffix("-"))
            if start >= len(data):
                self.send_error(416)
                return
            self.send_response(206)
            reported_start = start + 1 if self.path in server.bad_ranges else start
            self.send_header("Content-Range", f"bytes {reported_start}-{len(data) - 1}/{len(data)}")
            body = data[start:]
        else:
            self.send_response(200)
            body = data
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.path in server.truncate_once:
            server.truncate_once.remove(self.path)
            self.wfile.write(body[:len(body) // 2])
            self.wfile.flush()
            self.close_connection = True
        else:
            self.wfile.write(body)


class DataToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.downloads = self.directory / "downloads"
        self.downloads.mkdir()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.payloads = {}
        self.server.calls = []
        self.server.ignore_ranges = set()
        self.server.bad_ranges = set()
        self.server.truncate_once = set()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        raw_buffer = io.BytesIO()
        with zipfile.ZipFile(raw_buffer, "w") as archive:
            archive.writestr("city/example.csv", "station,occupied\nsample,1\n")
        self.raw_bytes = raw_buffer.getvalue()
        raw_parts = [self.raw_bytes[:8], self.raw_bytes[8:20], self.raw_bytes[20:35], self.raw_bytes[35:]]
        parts = [self.asset(f"data.zip.part{i:02d}", value) for i, value in enumerate(raw_parts, 1)]
        self.clean_bytes = tar_bytes([("nested/example.csv", b"station,occupied\nsample,1\n", None)])
        self.manifest = {
            "release_tag": "v1.0.0",
            "repository": "example/ev-data",
            "raw": {"filename": "data.zip", "bytes": len(self.raw_bytes), "sha256": digest(self.raw_bytes), "parts": parts},
            "cleaned": [
                {**self.asset("cleaned-beijing.tar.gz", self.clean_bytes), "city": "beijing"},
                {**self.asset("cleaned-shanghai.tar.gz", self.clean_bytes), "city": "shanghai"},
            ],
        }
        self.manifest_path = self.directory / "releases.json"
        self.write_manifest()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def asset(self, name, data):
        self.server.payloads["/" + name] = data
        return {"filename": name, "bytes": len(data), "sha256": digest(data), "url": self.base + "/" + name}

    def write_manifest(self, manifest=None):
        self.manifest_path.write_text(json.dumps(manifest or self.manifest), encoding="utf-8")

    def fetch(self, asset, **kwargs):
        return download.download_asset(asset, self.downloads, retry_delay=0, report=lambda message: None, **kwargs)

    def test_manifest_checks_integrity_fields_and_unsafe_names(self):
        cases = [
            ("digest", lambda m: m["cleaned"][0].update(sha256="TBD")),
            ("boolean_size", lambda m: m["cleaned"][0].update(bytes=True)),
            ("traversal", lambda m: m["cleaned"][0].update(filename="../outside.tar.gz")),
            ("sum", lambda m: m["raw"].update(bytes=m["raw"]["bytes"] + 1)),
            ("city", lambda m: m["cleaned"][1].update(city="beijing")),
            ("duplicate", lambda m: m["raw"]["parts"][0].update(filename="DATA.ZIP")),
            ("URL", lambda m: m["cleaned"][0].update(url="file:///secret")),
            ("device_name", lambda m: m["raw"]["parts"][0].update(filename="CON.bin")),
        ]
        for label, mutate in cases:
            with self.subTest(label=label):
                manifest = copy.deepcopy(self.manifest)
                mutate(manifest)
                self.write_manifest(manifest)
                with self.assertRaises(download.DataToolError):
                    download.load_manifest(self.manifest_path)
        self.assertEqual(self.server.calls, [])

    def test_city_download_cli_does_not_fetch_other_cities_or_raw(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = download.main(["--manifest", str(self.manifest_path), "--directory", str(self.downloads), "--city", "beijing"])
        self.assertEqual(code, 0)
        self.assertEqual([p[0] for p in self.server.calls], ["/cleaned-beijing.tar.gz"])
        self.assertEqual((self.downloads / "cleaned-beijing.tar.gz").read_bytes(), self.clean_bytes)

    def test_resume_206_and_reuse_valid_final(self):
        asset = self.manifest["cleaned"][0]
        partial = self.downloads / (asset["filename"] + ".partial")
        partial.write_bytes(self.clean_bytes[:17])
        final = self.fetch(asset, attempts=1)
        self.assertEqual(self.server.calls[0][1], "bytes=17-")
        self.assertEqual(final.read_bytes(), self.clean_bytes)
        self.fetch(asset, attempts=1)
        self.assertEqual(len(self.server.calls), 1)
        self.assertFalse(partial.exists())

    def test_ignored_range_200_overwrites_instead_of_appending(self):
        asset = self.manifest["cleaned"][0]
        self.server.ignore_ranges.add("/" + asset["filename"])
        (self.downloads / (asset["filename"] + ".partial")).write_bytes(b"wrong prefix")
        final = self.fetch(asset, attempts=1)
        self.assertEqual(final.read_bytes(), self.clean_bytes)
        self.assertEqual(final.stat().st_size, asset["bytes"])

    def test_bad_206_range_cannot_corrupt_saved_prefix(self):
        asset = self.manifest["cleaned"][0]
        self.server.bad_ranges.add("/" + asset["filename"])
        partial = self.downloads / (asset["filename"] + ".partial")
        prefix = self.clean_bytes[:17]
        partial.write_bytes(prefix)
        with self.assertRaises(download.DataToolError):
            self.fetch(asset, attempts=1)
        self.assertEqual(partial.read_bytes(), prefix)
        self.assertFalse((self.downloads / asset["filename"]).exists())

    def test_interrupted_body_retries_with_a_range(self):
        data = bytes(range(256)) * 4
        asset = self.asset("interrupted.bin", data)
        self.server.truncate_once.add("/interrupted.bin")
        final = self.fetch(asset, attempts=2, chunk_size=16)
        self.assertEqual(final.read_bytes(), data)
        self.assertGreater(len(self.server.calls), 1)
        self.assertTrue(self.server.calls[-1][1].startswith("bytes="))

    def test_bad_checksum_never_replaces_existing_final(self):
        asset = self.manifest["cleaned"][0]
        final = self.downloads / asset["filename"]
        final.write_bytes(b"old data remains intact")
        self.server.payloads["/" + asset["filename"]] = b"x" * asset["bytes"]
        with self.assertRaises(download.DataToolError):
            self.fetch(asset, attempts=1)
        self.assertEqual(final.read_bytes(), b"old data remains intact")
        self.assertFalse((self.downloads / (asset["filename"] + ".partial")).exists())

    def test_raw_cli_reassembles_in_manifest_order(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = download.main(["--manifest", str(self.manifest_path), "--directory", str(self.downloads), "--kind", "raw"])
        self.assertEqual(code, 0)
        self.assertEqual((self.downloads / "data.zip").read_bytes(), self.raw_bytes)
        self.assertEqual(len(self.server.calls), 4)
        self.assertFalse((self.downloads / "data.zip.assembling").exists())
        with zipfile.ZipFile(self.downloads / "data.zip") as archive:
            self.assertIn("city/example.csv", archive.namelist())

    def test_bad_raw_chunk_is_rejected_before_assembly(self):
        for part in self.manifest["raw"]["parts"]:
            (self.downloads / part["filename"]).write_bytes(self.server.payloads["/" + part["filename"]])
        first = self.manifest["raw"]["parts"][0]
        (self.downloads / first["filename"]).write_bytes(b"x" * first["bytes"])
        with self.assertRaises(download.DataToolError):
            download.reassemble_raw(self.manifest["raw"], self.downloads)
        self.assertFalse((self.downloads / "data.zip").exists())

    def test_wrong_assembled_digest_preserves_previous_archive(self):
        for part in self.manifest["raw"]["parts"]:
            (self.downloads / part["filename"]).write_bytes(self.server.payloads["/" + part["filename"]])
        raw = copy.deepcopy(self.manifest["raw"])
        raw["sha256"] = "0" * 64
        final = self.downloads / "data.zip"
        final.write_bytes(b"previous archive")
        with self.assertRaises(download.DataToolError):
            download.reassemble_raw(raw, self.downloads)
        self.assertEqual(final.read_bytes(), b"previous archive")
        self.assertFalse((self.downloads / "data.zip.assembling").exists())

    def test_verifier_is_offline_and_city_missing_is_an_error(self):
        asset = self.manifest["cleaned"][0]
        (self.downloads / asset["filename"]).write_bytes(self.clean_bytes)
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            report = verify.verify_downloads(self.manifest, self.downloads)
            self.assertTrue(report["ok"])
            self.assertEqual(len(report["checked"]), 1)
            missing = verify.verify_downloads(self.manifest, self.downloads, kind="cleaned", cities=["shanghai"])
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["errors"][0]["filename"], "cleaned-shanghai.tar.gz")

    def test_verifier_detects_same_length_corruption_and_require_all(self):
        asset = self.manifest["cleaned"][0]
        (self.downloads / asset["filename"]).write_bytes(b"x" * asset["bytes"])
        report = verify.verify_downloads(self.manifest, self.downloads, kind="cleaned", require_all=True)
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["errors"]), 2)

    def test_manifest_only_needs_no_downloads_or_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), redirect_stdout(io.StringIO()):
            self.assertEqual(verify.main(["--manifest", str(self.manifest_path), "--manifest-only"]), 0)

    def test_safe_tar_extraction_accepts_only_regular_nested_data(self):
        archive = self.directory / "cleaned.tar.gz"
        archive.write_bytes(self.clean_bytes)
        destination = self.directory / "extracted" / "beijing"
        download.safe_extract_tar(archive, destination)
        self.assertEqual((destination / "nested" / "example.csv").read_bytes(), b"station,occupied\nsample,1\n")
        with self.assertRaises(download.DataToolError):
            download.safe_extract_tar(archive, destination)

    def test_tar_path_traversal_links_and_devices_are_rejected_atomically(self):
        cases = [
            ("../outside", b"bad", None), ("/absolute/file", b"bad", None),
            ("nested/../../outside", b"bad", None), ("C:/outside", b"bad", None),
            ("nested\\outside", b"bad", None), ("file:stream", b"bad", None),
            ("CON.txt", b"bad", None), ("nested/link", None, tarfile.SYMTYPE),
            ("nested/link", None, tarfile.LNKTYPE), ("fifo", None, tarfile.FIFOTYPE),
            ("device", None, tarfile.CHRTYPE),
        ]
        for i, entry in enumerate(cases):
            with self.subTest(name=entry[0], kind=entry[2]):
                archive = self.directory / f"unsafe{i}.tar.gz"
                archive.write_bytes(tar_bytes([("good.csv", b"good", None), entry]))
                destination = self.directory / f"unsafe-output-{i}"
                with self.assertRaises(download.DataToolError):
                    download.safe_extract_tar(archive, destination)
                self.assertFalse(destination.exists())
        self.assertFalse((self.directory / "outside").exists())
        self.assertEqual(list(self.directory.glob(".*.extract-*")), [])

    def test_tar_duplicate_and_file_parent_paths_are_rejected(self):
        fixtures = [
            [("data.csv", b"a", None), ("data.csv", b"b", None)],
            [("folder", b"a", None), ("folder/data.csv", b"b", None)],
        ]
        for i, entries in enumerate(fixtures):
            archive = self.directory / f"collision{i}.tar.gz"
            archive.write_bytes(tar_bytes(entries))
            with self.assertRaises(download.DataToolError):
                download.safe_extract_tar(archive, self.directory / f"collision{i}")

    def test_download_and_extract_refuse_existing_symlinks(self):
        target = self.directory / "must-not-change"
        target.write_bytes(b"original")
        link = self.downloads / self.manifest["cleaned"][0]["filename"]
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Creating symbolic links is not permitted on this platform")
        with self.assertRaises(download.DataToolError):
            self.fetch(self.manifest["cleaned"][0], attempts=1)
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(self.server.calls, [])

    def test_raw_cannot_silently_accept_city_or_tar_extraction_options(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = download.main(["--manifest", str(self.manifest_path), "--kind", "raw", "--extract"])
        self.assertEqual(code, 1)
        self.assertEqual(self.server.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
