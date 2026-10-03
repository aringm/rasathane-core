"""Verify the immutable Typst/PDF-font source release and its public readback."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

INFRA = Path(__file__).resolve().parent
OUTPUT = INFRA / "vendor/source-supplement/typst-0.15.1"
LICENSES = INFRA / "vendor/tooling/typst-licenses"
FILENAME = "Rasathane-Typst-source-supplement-0.15.1.tar.gz"
SOURCE_URL = (
    "https://github.com/aringm/rasathane-core/releases/download/native-sources-0.5.0/" + FILENAME
)
BUNDLE_BYTES = 25302608
BUNDLE_SHA = "2274abfae7787fcbda874d6f5214fb8dc493ecb2551e047885ca3b09e6900273"
MANIFEST_SHA = "f7cd11e72ade5bcc15b1a63b0c8d6a76442b9e0e3069c89d8a2ce60be974a430"
SOURCE_MANIFEST_SHA = "a7115565e2784ee6249e3d4144b30f52d8e1d010462dfda457e5049c9b106b31"


def safe(path: Path, base: Path) -> Path:
    path.resolve().relative_to(base.resolve())
    for parent in [path, *path.parents]:
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError("Source staging contains a symlink or junction")
        if parent == base:
            break
    return path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def publication_matches(record: dict[str, Any]) -> bool:
    return (
        record.get("url") == SOURCE_URL
        and record.get("remote_full_stream_verified") is True
        and record.get("bytes") == BUNDLE_BYTES
        and record.get("sha256") == BUNDLE_SHA
        and record.get("bundle_manifest_sha256") == MANIFEST_SHA
    )


def verify() -> dict[str, Any]:
    failures: list[str] = []
    files = 0
    for name, expected in [
        (FILENAME, BUNDLE_SHA),
        ("BUNDLE-MANIFEST.json", MANIFEST_SHA),
        ("SOURCE-MANIFEST.json", SOURCE_MANIFEST_SHA),
    ]:
        path = safe(OUTPUT / name, OUTPUT)
        if not path.is_file() or digest(path) != expected:
            failures.append("MissingOrChanged:" + name)
    bundle = OUTPUT / FILENAME
    if bundle.is_file() and bundle.stat().st_size != BUNDLE_BYTES:
        failures.append("BundleSizeMismatch")
    if not failures:
        manifest = json.loads((OUTPUT / "BUNDLE-MANIFEST.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = safe(LICENSES / item["path"], LICENSES)
            if (
                not path.is_file()
                or path.stat().st_size != item["bytes"]
                or digest(path) != item["sha256"]
            ):
                failures.append("MissingOrChangedStaging:" + item["path"])
            files += 1
    published = False
    receipt = safe(OUTPUT / "PUBLICATION-RECEIPT.json", OUTPUT)
    if receipt.is_file():
        try:
            published = publication_matches(json.loads(receipt.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            failures.append("InvalidPublicationReceipt")
    return {
        "artifact": FILENAME,
        "bytes": BUNDLE_BYTES,
        "sha256": BUNDLE_SHA,
        "source_files": files,
        "publication_verified": published and not failures,
        "source_offer_complete": published and not failures,
        "failures": failures,
        "public_source_url": SOURCE_URL if published and not failures else None,
    }


def self_test() -> None:
    expected = {
        "url": SOURCE_URL,
        "remote_full_stream_verified": True,
        "bytes": BUNDLE_BYTES,
        "sha256": BUNDLE_SHA,
        "bundle_manifest_sha256": MANIFEST_SHA,
    }
    assert publication_matches(expected)
    for changes in [
        {"url": "https://example.org/source.tar.gz"},
        {"remote_full_stream_verified": False},
        {"remote_full_stream_verified": "true"},
        {"bytes": BUNDLE_BYTES + 1},
        {"sha256": "0" * 64},
        {"bundle_manifest_sha256": "0" * 64},
    ]:
        assert not publication_matches({**expected, **changes})
    assert not publication_matches({})
    try:
        safe(OUTPUT / "../outside.txt", OUTPUT)
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe staging traversal accepted")
    print("Source supplement receipt/path tests passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        try:
            result = verify()
        except (OSError, ValueError, KeyError, TypeError):
            result = {"source_offer_complete": False, "failures": ["InvalidSourceStaging"]}
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(
            2 if result["failures"] or (args.release and not result["source_offer_complete"]) else 0
        )
