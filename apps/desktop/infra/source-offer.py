"""Pinned native kaynaklarını ve tam lisans metinlerini release için hazırlar.

Yalnız checkout içindeki staging'e yazar; model, binary veya kullanıcı DB'si indirmez.
Kaynak eşlemesinin açık kabul engelleri varsa build yerel inceleme artefaktı üretir
ve exit 2 döndürür. verify --release eksik sunumu başarılı saymaz.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

INFRA = Path(__file__).resolve().parent
ROOT = INFRA.parents[2]
MANIFEST = INFRA / "source-offer-manifest.json"
STAGING = INFRA / "vendor/source-offer"
LICENSES = INFRA / "vendor/licenses/upstream"
PUBLIC_SOURCE_URL = (
    "https://github.com/aringm/rasathane-core/releases/download/native-sources-0.5.0/"
    "Rasathane-native-corresponding-source-0.5.0.tar.gz"
)
PUBLIC_REDIRECT_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
ALLOWED_HOSTS = {
    "github.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "files.pythonhosted.org",
    "ffmpeg.org",
    "deb.debian.org",
    "ftp.osuosl.org",
    "code.videolan.org",
    "gitlab.com",
    "bitbucket.org",
    "repo-source.bitbucket.org",
    "bbuseruploads.s3.amazonaws.com",
    "downloads.sourceforge.net",
    "sourceforge.net",
    "www.nasm.us",
    "ftp.gnu.org",
    "gcc.gnu.org",
}


def safe_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not (host in ALLOWED_HOSTS or host.endswith(".dl.sourceforge.net"))
    ):
        raise ValueError("Kaynak indirme adresi izinli HTTPS provider değil.")
    return value


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        return super().redirect_request(req, fp, code, msg, headers, safe_url(newurl))


class PublicationRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        safe_url(newurl)
        if urllib.parse.urlsplit(newurl).hostname not in PUBLIC_REDIRECT_HOSTS:
            raise ValueError("Public kaynak yönlendirmesi izinli GitHub host'u değil.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def publication_matches(record: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        record.get("schema_version") == "1.0"
        and record.get("remote_full_stream_verified") is True
        and record.get("url") == PUBLIC_SOURCE_URL
        and all(record.get(key) == value for key, value in expected.items())
    )


def publication_expected(output: Path) -> dict[str, Any]:
    info = json.loads((output / "BUNDLE-MANIFEST.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", info["artifact"]):
        raise ValueError("Kaynak bundle adı geçersiz.")
    artifact = contained_file(output / info["artifact"], output)
    if not artifact.is_file() or artifact.stat().st_size != info["bytes"]:
        raise ValueError("Yerel kaynak bundle boyutu doğrulanamadı.")
    if fingerprint(artifact) != info["sha256"]:
        raise ValueError("Yerel kaynak bundle SHA256 doğrulanamadı.")
    return {
        "sha256": info["sha256"],
        "bytes": info["bytes"],
        "source_manifest_sha256": fingerprint(MANIFEST),
        "bundle_manifest_sha256": fingerprint(output / "BUNDLE-MANIFEST.json"),
        "source_receipt_sha256": fingerprint(output / "SOURCE-RECEIPT.json"),
    }


def record_publication(output: Path, url: str) -> dict[str, Any]:
    if url != PUBLIC_SOURCE_URL:
        raise ValueError("Publication URL exact Rasathane kaynak release adresi olmalı.")
    initial = publication_expected(output)
    source_receipt = verify(load_manifest(), output)
    if source_receipt["failures"] or not source_receipt["corresponding_sources_prepared"]:
        raise ValueError("Yerel corresponding source girdileri doğrulanamadı.")
    opener = urllib.request.build_opener(PublicationRedirect())
    request = urllib.request.Request(
        safe_url(url),
        headers={
            "User-Agent": "Rasathane-source-offer/0.5",
            "Accept": "application/octet-stream",
            "Accept-Encoding": "identity",
        },
    )
    digest = hashlib.sha256()
    size = 0
    # Public bytes diske kaydedilmez; sadece sabit boyutlu bellek buffer'ı hash'lenir.
    with opener.open(request, timeout=60) as response:
        if response.status != 200:
            raise ValueError("Public kaynak indirmesi HTTP200 değil.")
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != initial["bytes"]:
            raise ValueError("Public kaynak boyutu yerel artefaktla uyuşmadı.")
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > initial["bytes"]:
                raise ValueError("Public kaynak boyutu sınırı aşıldı.")
            digest.update(chunk)
    if size != initial["bytes"] or digest.hexdigest() != initial["sha256"]:
        raise ValueError("Public kaynak full-stream SHA256/boyut eşleşmedi.")
    if publication_expected(output) != initial:
        raise ValueError("Readback sırasında yerel bundle veya makbuz değişti.")
    receipt = {
        "schema_version": "1.0",
        "product": "Rasathane",
        "version": "0.5.0",
        "url": url,
        "remote_full_stream_verified": True,
        "verified_at_utc": datetime.now(UTC).isoformat(),
        **initial,
    }
    write_json(output / "PUBLICATION-RECEIPT.json", receipt)
    return receipt


def fingerprint(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def contained_file(file: Path, base: Path) -> Path:
    file.resolve().relative_to(base.resolve())
    for parent in [file, *file.parents]:
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError("Kaynak/lisans staging'i symlink/junction içeremez.")
        if parent == base:
            break
    return file


def checked_staging(value: Path) -> Path:
    resolved = value.resolve()
    allowed = [STAGING.resolve(), (ROOT / ".local").resolve()]
    if not any(resolved.is_relative_to(base) and resolved != base for base in allowed):
        raise ValueError(
            "Kaynak sunumu çıktısı vendor/source-offer veya .local altındaki bir klasör olmalı."
        )
    for parent in [value, *value.parents]:
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError("Staging symlink/junction içermemeli.")
        if parent == ROOT:
            break
    return resolved


def load_manifest() -> dict[str, Any]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    if value.get("schema_version") != "1.0" or value.get("product") != "Rasathane":
        raise ValueError("Kaynak sunumu manifest şeması desteklenmiyor.")
    identifiers: set[str] = set()
    filenames: set[str] = set()
    for entry in value["archives"]:
        if not re.fullmatch(r"[a-z0-9-]+", entry["id"]) or entry["id"] in identifiers:
            raise ValueError("Kaynak component kimliği geçersiz veya mükerrer.")
        if (
            not re.fullmatch(r"[a-zA-Z0-9._-]+", entry["filename"])
            or entry["filename"] in filenames
        ):
            raise ValueError("Kaynak dosya adı geçersiz veya mükerrer.")
        if not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
            raise ValueError("Kaynak SHA256 sabit olmalı.")
        if entry["kind"] not in {"tar", "file"} or not 0 < entry["max_bytes"] <= 256 * 1024 * 1024:
            raise ValueError("Kaynak biçimi veya boyut sınırı geçersiz.")
        safe_url(entry["url"])
        identifiers.add(entry["id"])
        filenames.add(entry["filename"])
    for entry in value["reciprocal_inventory"]:
        if not entry["sources"] or not set(entry["sources"]).issubset(identifiers):
            raise ValueError("Reciprocal bileşenin sabit corresponding source kaydı eksik.")
    return value


def download(entry: dict[str, Any], destination: Path) -> Path:
    target = contained_file(destination / entry["filename"], destination)
    if target.exists():
        if fingerprint(target) != entry["sha256"]:
            raise ValueError(f"Mevcut kaynak SHA256 uyuşmadı: {entry['id']}")
        return target
    partial = contained_file(target.with_name(target.name + ".partial"), destination)
    opener = urllib.request.build_opener(SafeRedirect())
    request = urllib.request.Request(
        safe_url(entry["url"]), headers={"User-Agent": "Rasathane-source-offer/0.5"}
    )
    digest = hashlib.sha256()
    size = 0
    with opener.open(request, timeout=60) as response, partial.open("wb") as stream:
        if response.status != 200:
            raise ValueError(f"Kaynak indirilemedi: {entry['id']}")
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > entry["max_bytes"]:
                raise ValueError(f"Kaynak boyut sınırı aşıldı: {entry['id']}")
            digest.update(chunk)
            stream.write(chunk)
    if not size or digest.hexdigest() != entry["sha256"] or fingerprint(partial) != entry["sha256"]:
        raise ValueError(f"İndirilen kaynak SHA256 uyuşmadı: {entry['id']}")
    partial.replace(target)
    return target


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and ":" not in name
    )


def is_notice(name: str) -> bool:
    lower = PurePosixPath(name).name.lower()
    return lower.startswith(("license", "copying", "notice", "copyright"))


def license_records(entry: dict[str, Any], archive: Path) -> list[dict[str, Any]]:
    if entry["kind"] != "tar":
        return []
    records = []
    with tarfile.open(archive, "r:*") as source:
        for member in source:
            if not safe_member(member.name):
                raise ValueError(f"Kaynak arşivinde güvensiz yol: {entry['id']}")
            # extract()/extractall() kullanılmaz; symlink/hardlink dosyaya yazılmaz.
            if not member.isfile() or member.size > 1024 * 1024 or not is_notice(member.name):
                continue
            reader = source.extractfile(member)
            if reader is None:
                continue
            content = reader.read(1024 * 1024 + 1)
            if not content or len(content) > 1024 * 1024 or b"\x00" in content[:1024]:
                continue
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                # Bazı upstream eski copyright metinleri Latin-1 kullanır;
                # byte'lar aynen korunur, transcoding yapılmaz.
                pass
            digest = hashlib.sha256(content).hexdigest()
            directory = contained_file(LICENSES / entry["id"], LICENSES)
            directory.mkdir(parents=True, exist_ok=True)
            target = contained_file(directory / f"{digest}.txt", LICENSES)
            target.write_bytes(content)
            records.append(
                {
                    "component": entry["id"],
                    "archive_member": member.name,
                    "path": target.relative_to(LICENSES).as_posix(),
                    "bytes": len(content),
                    "sha256": digest,
                }
            )
    return records


def write_json(file: Path, value: Any) -> None:
    partial = contained_file(file.with_name(file.name + ".partial"), file.parent)
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    partial.replace(file)


def prepare(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    archives = checked_staging(output / "archives")
    archives.mkdir(parents=True, exist_ok=True)
    LICENSES.mkdir(parents=True, exist_ok=True)
    license_files = []
    sources = []
    failures = []
    for entry in manifest["archives"]:
        try:
            print(f"Kaynak doğrulanıyor: {entry['id']}", flush=True)
            archive = download(entry, archives)
            license_files.extend(license_records(entry, archive))
            sources.append(
                {
                    "id": entry["id"],
                    "filename": entry["filename"],
                    "bytes": archive.stat().st_size,
                    "sha256": fingerprint(archive),
                }
            )
        except (OSError, ValueError, tarfile.TarError, urllib.error.URLError) as error:
            # Signed redirect query'leri veya ortam sırları hata çıktısına alınmaz.
            failures.append({"component": entry["id"], "reason": type(error).__name__})
            print(f"Kaynak hazırlanamadı: {entry['id']} ({type(error).__name__})", flush=True)
    receipt = {
        "schema_version": "1.0",
        "product": manifest["product"],
        "version": manifest["version"],
        "manifest_sha256": fingerprint(MANIFEST),
        "sources": sources,
        "license_files": license_files,
        "failures": failures,
        "release_blockers": manifest["release_blockers"],
        "reciprocal_inventory": manifest["reciprocal_inventory"],
        "corresponding_sources_prepared": not failures,
        "source_offer_complete": not failures and not manifest["release_blockers"],
    }
    write_json(output / "SOURCE-RECEIPT.json", receipt)
    write_json(
        LICENSES / "LICENSE-MANIFEST.json",
        {
            "manifest_sha256": fingerprint(MANIFEST),
            "files": license_files,
            "failures": failures,
            "release_blockers": manifest["release_blockers"],
            "corresponding_sources_prepared": receipt["corresponding_sources_prepared"],
            "source_offer_complete": receipt["source_offer_complete"],
        },
    )
    return receipt


def verify(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    file = output / "SOURCE-RECEIPT.json"
    if not file.is_file():
        raise ValueError("Kaynak makbuzu yok; önce prepare/build çalıştırın.")
    receipt = json.loads(file.read_text(encoding="utf-8"))
    failures = list(receipt.get("failures", []))
    if receipt.get("manifest_sha256") != fingerprint(MANIFEST):
        failures.append({"component": "manifest", "reason": "ManifestChanged"})
    found = {entry["id"]: entry for entry in receipt["sources"]}
    expected_ids = {entry["id"] for entry in manifest["archives"]}
    if len(found) != len(receipt["sources"]) or set(found) != expected_ids:
        failures.append({"component": "receipt", "reason": "SourceInventoryChanged"})
    for entry in manifest["archives"]:
        source = contained_file(output / "archives" / entry["filename"], output)
        record = found.get(entry["id"], {})
        if record.get("filename") != entry["filename"] or record.get("sha256") != entry["sha256"]:
            failures.append({"component": entry["id"], "reason": "SourceReceiptChanged"})
        if (
            entry["id"] not in found
            or not source.is_file()
            or fingerprint(source) != entry["sha256"]
        ):
            failures.append({"component": entry["id"], "reason": "MissingOrChangedSource"})
    for entry in receipt["license_files"]:
        name = entry["path"]
        if not safe_member(name):
            raise ValueError("Lisans makbuzunda güvensiz yol.")
        source = contained_file(LICENSES / name, LICENSES)
        if not source.is_file() or fingerprint(source) != entry["sha256"]:
            failures.append({"component": entry["component"], "reason": "MissingOrChangedLicense"})
    receipt["failures"] = failures
    receipt["release_blockers"] = manifest["release_blockers"]
    receipt["reciprocal_inventory"] = manifest["reciprocal_inventory"]
    receipt["corresponding_sources_prepared"] = not failures
    publication = output / "PUBLICATION-RECEIPT.json"
    if not failures and publication.is_file():
        try:
            record = json.loads(publication.read_text(encoding="utf-8"))
            if publication_matches(record, publication_expected(output)):
                receipt["release_blockers"] = [
                    gate
                    for gate in manifest["release_blockers"]
                    if gate.get("id") != "published_source_access"
                ]
                receipt["publication_verified"] = True
                receipt["public_source_url"] = PUBLIC_SOURCE_URL
        except (OSError, ValueError, KeyError, TypeError):
            # Geçersiz veya eski publication makbuzu source erişim gate'ini kapatmaz.
            receipt["publication_verified"] = False
    receipt["source_offer_complete"] = not failures and not receipt["release_blockers"]
    return receipt


def bundle(output: Path, receipt: dict[str, Any]) -> Path:
    target = output / "Rasathane-native-corresponding-source-0.5.0.tar.gz"
    partial = contained_file(target.with_name(target.name + ".partial"), output)
    files = [
        (MANIFEST, "source-offer-manifest.json"),
        (INFRA / "SOURCE-OFFER.md", "SOURCE-OFFER.md"),
        (Path(__file__), "source-offer.py"),
        (output / "SOURCE-RECEIPT.json", "SOURCE-RECEIPT.json"),
    ]
    files.extend(
        (output / "archives" / item["filename"], "archives/" + item["filename"])
        for item in receipt["sources"]
    )
    files.extend(
        (LICENSES / item["path"], "licenses/" + item["path"]) for item in receipt["license_files"]
    )
    with (
        partial.open("wb") as binary,
        gzip.GzipFile(fileobj=binary, mode="wb", mtime=0, filename="") as zipped,
    ):
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for source, name in sorted(set(files), key=lambda row: row[1]):
                entry = archive.gettarinfo(str(source), arcname=name)
                entry.mtime = 0
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ""
                entry.mode = 0o644
                with source.open("rb") as stream:
                    archive.addfile(entry, stream)
    partial.replace(target)
    write_json(
        output / "BUNDLE-MANIFEST.json",
        {
            "artifact": target.name,
            "bytes": target.stat().st_size,
            "sha256": fingerprint(target),
            "source_offer_complete": receipt["source_offer_complete"],
            "corresponding_sources_prepared": receipt["corresponding_sources_prepared"],
            "release_blockers": receipt["release_blockers"],
            "failures": receipt["failures"],
        },
    )
    return target


def self_test() -> None:
    for value in ["../COPYING", "/COPYING", "C:/COPYING", "safe\\..\\COPYING", "//server/share"]:
        assert not safe_member(value), value
    assert safe_member("component/source/COPYING")
    for value in [
        "http://github.com/source",
        "https://github.com.evil/source",
        "https://u:p@github.com/source",
        "https://github.com:444/source",
    ]:
        try:
            safe_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)
    assert safe_url("https://codeload.github.com/a/b/tar.gz/fixed")
    for value in [ROOT, ROOT / "apps", ROOT / ".local"]:
        try:
            checked_staging(value)
        except ValueError:
            pass
        else:
            raise AssertionError(str(value))
    assert checked_staging(ROOT / ".local/source-review") == ROOT / ".local/source-review"
    assert is_notice("a/LICENSE.txt") and not is_notice("a/bin.dll")
    manifest = load_manifest()
    assert all(entry["sources"] for entry in manifest["reciprocal_inventory"])
    assert manifest["provenance"]["pyav_wheel"]["ffmpeg_version"] == "8.1.2"
    assert manifest["release_blockers"]
    assert not manifest["provenance"]["msys_binary_mapping_verified"]
    expected = {
        "sha256": "a" * 64,
        "bytes": 10,
        "source_manifest_sha256": "b" * 64,
        "bundle_manifest_sha256": "c" * 64,
        "source_receipt_sha256": "d" * 64,
    }
    receipt = {
        "schema_version": "1.0",
        "remote_full_stream_verified": True,
        "url": PUBLIC_SOURCE_URL,
        **expected,
    }
    assert publication_matches(receipt, expected)
    for changes in [
        {"sha256": "e" * 64},
        {"bytes": 11},
        {"url": PUBLIC_SOURCE_URL + "?x=1"},
        {"source_receipt_sha256": "e" * 64},
        {"remote_full_stream_verified": "true"},
        {"url": "https://github.com/aringm/rasathane-core/releases/download/../a"},
    ]:
        assert not publication_matches({**receipt, **changes}, expected)
    # Lisans tespiti ordinary dosyaları kapsar; bir tar symlink metin sayılmaz.
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo("source/LICENSE")
        member.type = tarfile.SYMTYPE
        member.linkname = "/outside"
        archive.addfile(member)
    with tarfile.open(fileobj=io.BytesIO(data.getvalue())) as archive:
        assert not archive.getmembers()[0].isfile()
    print("8 kaynak sunumu doğrulama grubu geçti; ağ ve filesystem yazması yapılmadı.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["prepare", "build", "verify", "self-test", "record-publication"]
    )
    parser.add_argument("--url", help="Exact public kaynak release URL'si")
    parser.add_argument("--output", type=Path, default=STAGING / "0.5.0")
    parser.add_argument("--release", action="store_true", help="Açık kabul engelinde exit 2")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    output = checked_staging(args.output)
    # Lisans staging'i de canonical checkout dışına yönlendirilemez.
    for directory in [LICENSES, *LICENSES.parents]:
        if directory.is_symlink() or (
            hasattr(directory, "is_junction") and directory.is_junction()
        ):
            raise ValueError("Lisans staging sınırı symlink/junction içeriyor.")
        if directory == ROOT:
            break
    manifest = load_manifest()
    if args.command == "record-publication":
        if not args.url:
            parser.error("record-publication için --url gerekli.")
        receipt = record_publication(output, args.url)
        print(json.dumps(receipt, ensure_ascii=False))
        return 0
    if args.command in {"prepare", "build"}:
        if (output / "PUBLICATION-RECEIPT.json").exists():
            raise ValueError(
                "Yayınlanmış source staging'i sabittir; yeni içerik yeni release klasörüne yazılır."
            )
        output.mkdir(parents=True, exist_ok=True)
        receipt = prepare(manifest, output)
    else:
        receipt = verify(manifest, output)
    if args.command == "verify" and args.release:
        bundle_manifest = output / "BUNDLE-MANIFEST.json"
        if not bundle_manifest.is_file():
            receipt["failures"].append({"component": "bundle", "reason": "MissingBundleManifest"})
        else:
            info = json.loads(bundle_manifest.read_text(encoding="utf-8"))
            if not re.fullmatch(r"[a-zA-Z0-9._-]+", info["artifact"]):
                raise ValueError("Kaynak bundle makbuzunda geçersiz dosya adı.")
            archive = contained_file(output / info["artifact"], output)
            if not archive.is_file() or fingerprint(archive) != info["sha256"]:
                receipt["failures"].append(
                    {"component": "bundle", "reason": "MissingOrChangedBundle"}
                )
            elif (
                info.get("corresponding_sources_prepared")
                != receipt["corresponding_sources_prepared"]
            ):
                receipt["failures"].append({"component": "bundle", "reason": "StaleBundleReceipt"})
        if receipt["failures"]:
            receipt["corresponding_sources_prepared"] = False
            receipt["source_offer_complete"] = False
    artifact = None
    if args.command == "build" and not receipt["failures"]:
        artifact = str(bundle(output, receipt))
    print(
        json.dumps(
            {
                "sources": len(receipt["sources"]),
                "license_files": len(receipt["license_files"]),
                "failures": receipt["failures"],
                "release_blockers": receipt["release_blockers"],
                "source_offer_complete": receipt["source_offer_complete"],
                "corresponding_sources_prepared": receipt["corresponding_sources_prepared"],
                "artifact": artifact,
                "publication_verified": receipt.get("publication_verified", False),
                "public_source_url": receipt.get("public_source_url"),
            },
            ensure_ascii=False,
        )
    )
    if receipt["failures"] or (
        (args.command == "build" or args.release) and not receipt["source_offer_complete"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"Kaynak sunumu hazırlanamadı: {type(error).__name__}")
        raise SystemExit(2) from None
