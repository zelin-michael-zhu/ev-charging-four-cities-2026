# Download and verify the release data

Use Python 3.10 or later. The downloader, verifier and tests use the standard
library only; no package installation is needed.

Run these commands from the repository root. Default paths are resolved from
the scripts' location, so invoking a script by its absolute path from another
working directory also works. Explicit relative path options are relative to
your current working directory.

## Cleaned data

Download all four cleaned city archives:

```console
python scripts/download_data.py
```

The files listed in `data/releases.json` are downloaded into
`data/downloads/`. Select one or more cities:

```console
python scripts/download_data.py --city beijing
python scripts/download_data.py --city shanghai shenzhen
python scripts/download_data.py --city beijing --city chongqing
```

The release uses the city identifiers `beijing`, `shanghai`,
`shenzhen` and `chongqing`. Each archive's exact filename, byte
count, SHA256 and release URL are recorded in the manifest.

Optionally extract verified cleaned archives:

```console
python scripts/download_data.py --city beijing --extract
```

Extraction preserves the archive's relative layout inside `data/cleaned/beijing/`.
The extractor accepts regular files and directories only. It refuses traversal
paths, absolute paths, symbolic links, hard links, devices, duplicate members and
nonportable special paths. It stages extraction before publishing the directory,
does not apply archive ownership or permission metadata, and refuses an existing
nonempty destination. To extract another copy, use a different destination:

```console
python scripts/download_data.py --city beijing --extract --extract-directory data/another-copy
```

## Original raw archive

```console
python scripts/download_data.py --kind raw
```

The downloader fetches the four parts in manifest order, verifies every part,
and streams them into `data/downloads/data.zip`. It checks the assembled
archive's exact size and SHA256 before replacing any existing archive.

For release v1.0.0, the original archive is 4,547,739,657 bytes: three parts of
1,500,000,000 bytes and a final part of 47,739,657 bytes. During assembly, the
parts and complete archive coexist, requiring at least about 9.1 GB of free
space, plus filesystem overhead and any other retained files. Parts are kept
after assembly. `--city` and `--extract` apply only to cleaned data;
the tool does not automatically unpack the original raw ZIP.

## Local integrity checks

No verifier command makes a network request. Check all downloaded assets that
are currently present:

```console
python scripts/verify_data.py
```

Missing unrequested files are reported as skipped. A corrupt present file, a
symbolic-link asset, or finding no selected downloaded assets causes a nonzero
exit status. An explicitly selected city must be present:

```console
python scripts/verify_data.py --kind cleaned --city beijing
python scripts/verify_data.py --kind cleaned --require-all
python scripts/verify_data.py --kind raw
python scripts/verify_data.py --json
```

For raw data, `--require-all` requires both every part and the assembled ZIP.
Without this flag, whichever of these files are present are checked.

Validate only the manifest schema and checksum format:

```console
python scripts/verify_data.py --manifest-only
```

This command checks metadata, not the contents or availability of remote assets.
Archive checksums prove that downloaded bytes match the manifest; they do not
independently validate the scientific interpretation of the data or detect later
edits to an extracted file.

## Retry, resume and custom locations

```console
python scripts/download_data.py --city beijing --attempts 5 --timeout 120
python scripts/download_data.py --directory /path/to/downloads
python scripts/verify_data.py --directory /path/to/downloads
python scripts/download_data.py --manifest /path/to/releases.json --city beijing
```

Interrupted downloads keep a `.partial` file. A later run requests the
remaining bytes and appends only when an HTTP 206 response has a matching
Content-Range. If the server returns HTTP 200 instead, the partial file is
overwritten from the beginning. Completed files are reused only after size and
SHA256 verification. A checksum failure discards the partial download and
retries; a previous final file is retained until a replacement verifies.
Do not run multiple downloader instances against the same output directory.

The manifest rejects missing or malformed checksums rather than offering an
unchecked download mode. Public release URLs normally need no GitHub login.

## Small-file tests and CI

```console
python -m unittest discover -s scripts -p "test_data_tools.py" -v
```

Tests create tiny synthetic archives and a local HTTP server. They cover 206
resume, ignored Range, interrupted transfers, checksum failures, ordered raw
assembly, offline verification and unsafe tar members. They never fetch the
multi-gigabyte public release. GitHub Actions runs these tests on Linux and
Windows with Python 3.10 and 3.12, and validates the release manifest.
