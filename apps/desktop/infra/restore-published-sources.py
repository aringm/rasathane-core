"""Restore fixed public source artifacts without replacing existing files."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import runpy
import tarfile
import urllib.request
from pathlib import Path
from uuid import uuid4

INFRA = Path(__file__).resolve().parent
SOURCE = runpy.run_path(str(INFRA / "source-offer.py"))
SUPPLEMENT = runpy.run_path(str(INFRA / "verify-source-supplement.py"))
BASE_URL = "https://github.com/aringm/rasathane-core/releases/download/native-sources-0.5.0/"
SPECS = {
    "native": {
        "artifact": "Rasathane-native-corresponding-source-0.5.0.tar.gz",
        "bytes": 244061209,
        "sha256": "6f2d08d6634d43879a7d98e6af40cf4c126c5f9d6f8f908ce882f5d6aa272dbf",
        "manifest": "BUNDLE-MANIFEST.json",
        "manifest_bytes": 707,
        "manifest_sha256": "e08c5126954c8e9192a4023e21cb82f36bb885bc59ec9abd8dc8b4727c2c333b",
        "output": INFRA / "vendor/source-offer/0.5.0",
    },
    "typst": {
        "artifact": SUPPLEMENT["FILENAME"],
        "bytes": SUPPLEMENT["BUNDLE_BYTES"],
        "sha256": SUPPLEMENT["BUNDLE_SHA"],
        "manifest": "RASATHANE-TYPST-BUNDLE-MANIFEST.json",
        "manifest_bytes": 184504,
        "manifest_sha256": SUPPLEMENT["MANIFEST_SHA"],
        "output": SUPPLEMENT["OUTPUT"],
    },
}


def digest(path: Path) -> str:
    return SOURCE["fingerprint"](path)


def checked(path: Path) -> Path:
    return SOURCE["contained_file"](path, INFRA.parent)


def valid(path: Path, size: int, sha: str) -> bool:
    return path.is_file() and path.stat().st_size == size and digest(path) == sha


def public_file(name: str, size: int, sha: str, kind: str) -> Path:
    target = checked(INFRA.parent / ".local/public-source-downloads" / kind / name)
    if target.exists():
        if not valid(target, size, sha):
            raise ValueError("Existing download does not match; it is not overwritten")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = checked(target.with_name(target.name + "." + uuid4().hex + ".partial"))
    request = urllib.request.Request(
        BASE_URL + name,
        headers={"User-Agent": "Rasathane-public-source-restore", "Accept-Encoding": "identity"},
    )
    opener = urllib.request.build_opener(SOURCE["PublicationRedirect"]())
    h = hashlib.sha256()
    count = 0
    with opener.open(request, timeout=60) as response, partial.open("xb") as output:
        if response.status != 200:
            raise ValueError("Public artifact did not return HTTP200")
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > size:
                raise ValueError("Public source download exceeded pinned size")
            h.update(chunk)
            output.write(chunk)
    if count != size or h.hexdigest() != sha or not valid(partial, size, sha):
        raise ValueError("Public full-stream size/SHA does not match")
    # Hardlink fails if the destination was created concurrently; no overwrite.
    os.link(partial, target)
    partial.unlink()
    return target


def member_plan(archive: tarfile.TarFile, kind: str):
    output = SPECS[kind]["output"]
    if kind == "native":
        manifest_sha = digest(INFRA / "source-offer-manifest.json")
        receipt = json.load(archive.extractfile("SOURCE-RECEIPT.json"))
        if receipt["manifest_sha256"] != manifest_sha:
            raise ValueError("Published native source manifest differs from the checkout")
        expected = {"SOURCE-RECEIPT.json": None}
        expected.update({"archives/" + row["filename"]: row for row in receipt["sources"]})
        expected.update({"licenses/" + row["path"]: row for row in receipt["license_files"]})
    else:
        source_member = archive.extractfile("typst-0.15.1/SOURCE-MANIFEST.json").read()
        if hashlib.sha256(source_member).hexdigest() != SUPPLEMENT["SOURCE_MANIFEST_SHA"]:
            raise ValueError("Published supplement source manifest differs")
        receipt = json.loads(source_member)
        expected = {"typst-0.15.1/" + row["path"]: row for row in receipt["files"]}
        expected["typst-0.15.1/SOURCE-MANIFEST.json"] = None
    plan = []
    seen = set()
    for member in archive.getmembers():
        if member.name in seen or not member.isfile() or not SOURCE["safe_member"](member.name):
            raise ValueError("Unsafe, duplicate or non-file source member")
        seen.add(member.name)
        if member.name not in expected:
            if kind == "native" and member.name in [
                "source-offer.py",
                "source-offer-manifest.json",
                "SOURCE-OFFER.md",
            ]:
                continue  # Preserve current tracked tooling/docs; archive keeps original bytes.
            raise ValueError("Unexpected source member")
        if kind == "native":
            target = (
                INFRA / "vendor/licenses/upstream" / member.name.removeprefix("licenses/")
                if member.name.startswith("licenses/")
                else output / member.name
            )
        else:
            relative = member.name.removeprefix("typst-0.15.1/")
            target = (
                output / relative
                if relative == "SOURCE-MANIFEST.json"
                else SUPPLEMENT["LICENSES"] / relative
            )
        h = hashlib.sha256()
        with archive.extractfile(member) as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
        row = expected[member.name]
        if row and (row["bytes"] != member.size or row["sha256"] != h.hexdigest()):
            raise ValueError("Published source member does not match its receipt")
        target = checked(target)
        if target.exists() and not valid(target, member.size, h.hexdigest()):
            raise ValueError("Existing staging file differs; no files were replaced")
        plan.append((member, target, h.hexdigest()))
    if not set(expected).issubset(seen):
        raise ValueError("Published source archive is incomplete")
    return plan


def copy_missing(source: Path, target: Path) -> None:
    target = checked(target)
    if target.exists():
        if not valid(target, source.stat().st_size, digest(source)):
            raise ValueError("Existing artifact differs; it is not overwritten")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as stream, target.open("xb") as output:
        while chunk := stream.read(1024 * 1024):
            output.write(chunk)


def restore(
    kind: str, local_archive: Path | None, local_manifest: Path | None, validate_only: bool
) -> dict:
    spec = SPECS[kind]
    source = local_archive or public_file(spec["artifact"], spec["bytes"], spec["sha256"], kind)
    manifest = local_manifest or public_file(
        spec["manifest"], spec["manifest_bytes"], spec["manifest_sha256"], kind
    )
    if not valid(source, spec["bytes"], spec["sha256"]):
        raise ValueError("Published source artifact SHA/size mismatch")
    if not valid(manifest, spec["manifest_bytes"], spec["manifest_sha256"]):
        raise ValueError("Published bundle manifest SHA/size mismatch")
    for original, name in [(source, spec["artifact"]), (manifest, "BUNDLE-MANIFEST.json")]:
        target = checked(spec["output"] / name)
        if target.exists() and not valid(target, original.stat().st_size, digest(original)):
            raise ValueError("Existing artifact differs; no staging file was replaced")
    with tarfile.open(source, "r:gz") as archive:
        plan = member_plan(archive, kind)
        license_inventory = None
        if kind == "native":
            receipt = json.load(archive.extractfile("SOURCE-RECEIPT.json"))
            data = {
                "manifest_sha256": receipt["manifest_sha256"],
                "files": receipt["license_files"],
                "failures": receipt["failures"],
                "release_blockers": receipt["release_blockers"],
                "corresponding_sources_prepared": receipt["corresponding_sources_prepared"],
                "source_offer_complete": receipt["source_offer_complete"],
            }
            license_inventory = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
            license_target = checked(INFRA / "vendor/licenses/upstream/LICENSE-MANIFEST.json")
            if license_target.exists() and json.loads(license_target.read_bytes()) != data:
                raise ValueError("Existing license inventory differs; no file was replaced")
        if not validate_only:
            for member, target, sha in plan:
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, target.open("xb") as output:
                    while chunk := stream.read(1024 * 1024):
                        output.write(chunk)
                if not valid(target, member.size, sha):
                    raise ValueError("Restored member SHA/size mismatch")
            copy_missing(source, spec["output"] / spec["artifact"])
            copy_missing(manifest, spec["output"] / "BUNDLE-MANIFEST.json")
            if license_inventory is not None and not license_target.exists():
                with license_target.open("xb") as output:
                    output.write(license_inventory)
    return {
        "kind": kind,
        "validated": True,
        "restored": not validate_only,
        "files": len(plan),
        "sha256": spec["sha256"],
    }


def self_test() -> None:
    receipt = json.dumps(
        {
            "manifest_sha256": digest(INFRA / "source-offer-manifest.json"),
            "sources": [],
            "license_files": [],
        }
    ).encode()
    original = SPECS["native"]["output"]
    SPECS["native"]["output"] = INFRA.parent / ".local" / ("restore-test-" + uuid4().hex)

    def fixture(extra: str | None = None, symlink: bool = False) -> io.BytesIO:
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode="w") as archive:
            member = tarfile.TarInfo("SOURCE-RECEIPT.json")
            member.size = len(receipt)
            archive.addfile(member, io.BytesIO(receipt))
            if extra:
                member = tarfile.TarInfo(extra)
                member.type = tarfile.SYMTYPE if symlink else tarfile.REGTYPE
                member.linkname = "SOURCE-RECEIPT.json" if symlink else ""
                archive.addfile(member, io.BytesIO())
        memory.seek(0)
        return memory

    try:
        with tarfile.open(fileobj=fixture()) as archive:
            assert len(member_plan(archive, "native")) == 1
        for name, link in [
            ("../escape", False),
            ("/absolute", False),
            ("C:/escape", False),
            ("licenses\\escape", False),
            ("SOURCE-RECEIPT.json", False),
            ("link", True),
        ]:
            try:
                with tarfile.open(fileobj=fixture(name, link)) as archive:
                    member_plan(archive, "native")
            except ValueError:
                pass
            else:
                raise AssertionError("Unsafe source archive accepted")
        SPECS["native"]["output"] = original
        preserved = INFRA / "source-offer-manifest.json"
        before = digest(preserved)
        try:
            copy_missing(INFRA / "SOURCE-OFFER.md", preserved)
        except ValueError:
            pass
        else:
            raise AssertionError("Existing mismatched staging accepted")
        assert digest(preserved) == before
    finally:
        SPECS["native"]["output"] = original
    print("Source restore path/link/duplicate/no-overwrite tests passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=SPECS, nargs="?")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--bundle-manifest", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            raise SystemExit(0)
        if args.kind is None:
            raise ValueError("A source artifact kind is required")
        print(
            json.dumps(
                restore(args.kind, args.archive, args.bundle_manifest, args.validate_only),
                ensure_ascii=False,
            )
        )
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        print("Public source restore failed; no existing file was replaced.")
        raise SystemExit(2) from None
