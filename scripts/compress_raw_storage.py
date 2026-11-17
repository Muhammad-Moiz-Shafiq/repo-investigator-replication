"""One-off migration: gzip the pilot's plain .json raw files in Supabase Storage.

The free tier caps object storage at 1 GB and the three pilot repos already
use 367 MB, almost all of it raw CI run JSON. Adding three busier repos would
go over, so raw files are now stored gzipped (see storage/s3_client.py).

This script converts the existing files without trusting that gzip "should"
be lossless. For every original it records a SHA-256, uploads a .json.gz copy
next to it, downloads that copy back, decompresses it and checks the hash
again. Results go to docs/dataset_snapshots/raw_compression_manifest.json.

Originals are only deleted with --delete-originals, and only for files the
manifest marks as verified. Run the cleaning comparison
(scripts/verify_compressed_cleaning.py) before doing that.

Usage:
  uv run python scripts/compress_raw_storage.py                      # compress + verify, keep originals
  uv run python scripts/compress_raw_storage.py --delete-originals   # after the checks pass
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from repo_investigator.storage.s3_client import make_storage_client

MANIFEST_PATH = Path(__file__).parent.parent / "docs" / "dataset_snapshots" / "raw_compression_manifest.json"


def list_files(storage, prefix: str) -> list[str]:
    """Recursively lists object paths under prefix. Supabase returns folders
    as entries with no id, so we descend into those."""
    paths, offset = [], 0
    while True:
        batch = storage.list(prefix, {"limit": 1000, "offset": offset})
        if not batch:
            break
        for entry in batch:
            full = f"{prefix}/{entry['name']}"
            if entry.get("id") is None:
                paths.extend(list_files(storage, full))
            else:
                paths.append(full)
        offset += len(batch)
    return paths


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compress_all(storage) -> list[dict]:
    originals = sorted(p for p in list_files(storage, "raw") if p.endswith(".json"))
    print(f"{len(originals)} plain .json files to convert")
    manifest = []
    for i, path in enumerate(originals, 1):
        original = storage.download(path)
        compressed = gzip.compress(original, mtime=0)
        if gzip.decompress(compressed) != original:
            raise RuntimeError(f"local round trip failed for {path}")

        gz_path = path + ".gz"
        options = {"content-type": "application/gzip", "upsert": "true"}
        storage.upload(gz_path, compressed, file_options=options)
        roundtrip = gzip.decompress(storage.download(gz_path))

        entry = {
            "path": path,
            "gz_path": gz_path,
            "sha256": sha256(original),
            "roundtrip_sha256": sha256(roundtrip),
            "bytes": len(original),
            "gz_bytes": len(compressed),
        }
        entry["verified"] = entry["sha256"] == entry["roundtrip_sha256"]
        manifest.append(entry)
        if i % 25 == 0 or not entry["verified"]:
            print(f"  {i}/{len(originals)} {path} verified={entry['verified']}")
    return manifest


def delete_originals(storage, manifest: list[dict]) -> None:
    unverified = [e["path"] for e in manifest if not e["verified"]]
    if unverified:
        raise RuntimeError(f"refusing to delete, {len(unverified)} files not verified: {unverified[:5]}")
    remaining = set(list_files(storage, "raw"))
    missing_gz = [e["gz_path"] for e in manifest if e["gz_path"] not in remaining]
    if missing_gz:
        raise RuntimeError(f"refusing to delete, compressed copies missing: {missing_gz[:5]}")
    to_delete = [e["path"] for e in manifest if e["path"] in remaining]
    for start in range(0, len(to_delete), 100):
        storage.remove(to_delete[start : start + 100])
    print(f"deleted {len(to_delete)} originals")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-originals", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    client = make_storage_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    storage = client.storage.from_(os.environ["SUPABASE_STORAGE_BUCKET"])

    if args.delete_originals:
        delete_originals(storage, json.loads(MANIFEST_PATH.read_text()))
        return

    manifest = compress_all(storage)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    ok = sum(e["verified"] for e in manifest)
    before = sum(e["bytes"] for e in manifest)
    after = sum(e["gz_bytes"] for e in manifest)
    print(f"verified {ok}/{len(manifest)}; {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
