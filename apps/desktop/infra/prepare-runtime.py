"""Pinned CPU engine ve NER/ASR modeli staging; kullanıcı modellerine yazmaz."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "infra/vendor/motor"
TOOLING = ROOT / "infra/vendor/tooling"
BINARY_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b10599/llama-b10599-bin-win-cpu-x64.zip"
BINARY_SHA = "d95eff420538b372273c5ee82258e238cc955ee3b5135443503d1fa4a38d8308"
TYPST_URL = (
    "https://github.com/typst/typst/releases/download/v0.15.1/typst-x86_64-pc-windows-msvc.zip"
)
TYPST_SHA = "19ce3551153c2fe7ee9fa2f95208310c8f4d3209fedb699e0333faf8913f6736"
MODELS = [
    (
        "ner",
        "akdeniz27/bert-base-turkish-cased-ner",
        "99995f7d2be4b3a28c74f0d36ee97f8c04ee0571",
        [
            "config.json",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "vocab.txt",
            "README.md",
        ],
    ),
    (
        "asr",
        "Systran/faster-whisper-small",
        "536b0662742c02347bc0e980a01041f333bce120",
        ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "README.md"],
    ),
]


def main() -> None:
    binary = MOTOR / "bin"
    # Mevcut staging de aynı upstream digest'ten yeniden doğrulanır.
    with urllib.request.urlopen(BINARY_URL, timeout=120) as response:
        payload = response.read(24 * 1024 * 1024 + 1)
    if hashlib.sha256(payload).hexdigest() != BINARY_SHA:
        raise ValueError("llama.cpp SHA256 uyuşmadı.")
    binary.mkdir(parents=True, exist_ok=True)
    binary_files = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            target = (binary / member.filename).resolve()
            target.relative_to(binary.resolve())
            if not member.is_dir():
                content = archive.read(member)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                binary_files.append(
                    {
                        "name": member.filename.replace("\\", "/"),
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
    entries = []
    with urllib.request.urlopen(TYPST_URL, timeout=120) as response:
        typst_payload = response.read(32 * 1024 * 1024 + 1)
    if hashlib.sha256(typst_payload).hexdigest() != TYPST_SHA:
        raise ValueError("Typst SHA256 uyuşmadı.")
    typst_root = TOOLING / "typst"
    typst_files = []
    with zipfile.ZipFile(io.BytesIO(typst_payload)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            parts = member.filename.replace("\\", "/").split("/")
            if parts[0] != "typst-x86_64-pc-windows-msvc" or len(parts) < 2:
                raise ValueError("Typst arşiv yapısı uyuşmadı.")
            relative = "/".join(parts[1:])
            target = (typst_root / relative).resolve()
            target.relative_to(typst_root.resolve())
            content = archive.read(member)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            typst_files.append(
                {
                    "name": relative,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    for kind, repo, revision, patterns in MODELS:
        destination = MOTOR / "modeller" / kind
        snapshot_download(
            repo_id=repo, revision=revision, allow_patterns=patterns, local_dir=destination
        )
        files = [
            {
                "name": str(file.relative_to(destination)),
                "bytes": file.stat().st_size,
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            }
            for file in sorted(destination.rglob("*"))
            if file.is_file() and ".cache" not in file.parts
        ]
        entries.append(
            {"kind": kind, "repo": repo, "revision": revision, "license": "MIT", "files": files}
        )
    (MOTOR / "motor-manifest.json").write_text(
        json.dumps(
            {
                "llama_cpp": {
                    "version": "b10599",
                    "upstream_archive_sha256": BINARY_SHA,
                    "files": binary_files,
                },
                "models": entries,
                "typst": {
                    "version": "0.15.1",
                    "upstream_archive_sha256": TYPST_SHA,
                    "files": typst_files,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        "Pinned CPU runtime ve NER/ASR modelleri hazır; GGUF modelleri kurulum sihirbazı indirir."
    )


if __name__ == "__main__":
    main()
