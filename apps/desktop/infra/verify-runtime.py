"""Paket girdilerini pinned staging manifest'ine göre yeniden doğrular."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "infra/vendor/motor"
ENGINE_SHA = "d95eff420538b372273c5ee82258e238cc955ee3b5135443503d1fa4a38d8308"
REVISIONS = {
    "ner": "99995f7d2be4b3a28c74f0d36ee97f8c04ee0571",
    "asr": "536b0662742c02347bc0e980a01041f333bce120",
}
TYPST_SHA = "19ce3551153c2fe7ee9fa2f95208310c8f4d3209fedb699e0333faf8913f6736"


def digest(file: Path) -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_files(root: Path, entries: list[dict[str, object]]) -> int:
    if not entries:
        raise ValueError(f"Dosya hash listesi eksik: {root}")
    checked = set()
    for entry in entries:
        file = (root / str(entry["name"])).resolve()
        file.relative_to(root.resolve())
        if not file.is_file() or file.stat().st_size != entry["bytes"]:
            raise ValueError(f"Runtime boyut/dosya uyuşmazlığı: {file}")
        if digest(file) != entry["sha256"]:
            raise ValueError(f"Runtime SHA256 uyuşmazlığı: {file}")
        checked.add(file)
    # HF metadata cache'i paket içindeki model değildir.
    actual = {
        file.resolve() for file in root.rglob("*") if file.is_file() and ".cache" not in file.parts
    }
    if actual != checked:
        raise ValueError(f"Manifest dışında runtime dosyaları var: {root}")
    return len(checked)


def main() -> None:
    manifest = json.loads((MOTOR / "motor-manifest.json").read_text(encoding="utf-8"))
    engine = manifest["llama_cpp"]
    if engine["version"] != "b10599" or engine["upstream_archive_sha256"] != ENGINE_SHA:
        raise ValueError("Pinned engine revision/hash uyuşmadı.")
    count = verify_files(MOTOR / "bin", engine.get("files", []))
    models = manifest["models"]
    if {item["kind"] for item in models} != set(REVISIONS):
        raise ValueError("NER/ASR model listesi uyuşmadı.")
    for item in models:
        if item["revision"] != REVISIONS[item["kind"]]:
            raise ValueError("Pinned model revision uyuşmadı.")
        count += verify_files(MOTOR / "modeller" / item["kind"], item["files"])
    typst = manifest["typst"]
    if typst["version"] != "0.15.1" or typst["upstream_archive_sha256"] != TYPST_SHA:
        raise ValueError("Pinned Typst revision/hash uyuşmadı.")
    count += verify_files(ROOT / "infra/vendor/tooling/typst", typst["files"])
    print(json.dumps({"runtime_files_verified": count, "engine": engine["version"]}))


if __name__ == "__main__":
    main()
