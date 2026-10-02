"""Frozen runtime envanteri ve dağıtılan wheel lisanslarını üretir (ağ kullanmaz)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "infra/vendor/licenses"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    components = []
    for runtime, packages in (
        ("sidecar", ROOT / ".venv/Lib/site-packages"),
        ("worker", ROOT / "infra/worker-runtime/.venv/Lib/site-packages"),
    ):
        if not packages.is_dir():
            raise FileNotFoundError(f"Runtime sync gerekli: {runtime}")
        for distribution in sorted(
            importlib.metadata.distributions(path=[str(packages)]),
            key=lambda value: value.metadata["Name"].lower(),
        ):
            name = distribution.metadata["Name"]
            files = []
            for relative in distribution.files or ():
                parts = str(relative).lower().replace("\\", "/").split("/")
                if not any(part.startswith(("license", "copying", "notice")) for part in parts):
                    continue
                source = Path(distribution.locate_file(relative))
                if not source.is_file() or source.stat().st_size > 1024 * 1024:
                    continue
                content = source.read_bytes()
                # Dist-info dışındaki büyük binary'ler paket lisansı değildir.
                if b"\x00" in content[:1024]:
                    continue
                # İç içe LICENSE/NOTICE adları birbirini ezmez; case-insensitive
                # Windows'ta da farklı metinler ayrı immutable dosyaya gider.
                fingerprint = hashlib.sha256(content).hexdigest()
                target = OUTPUT / runtime / name / f"{fingerprint}.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                files.append(
                    {
                        "path": str(target.relative_to(OUTPUT)).replace("\\", "/"),
                        "source_path": str(relative).replace("\\", "/"),
                        "sha256": fingerprint,
                    }
                )
            components.append(
                {
                    "type": "library",
                    "name": name,
                    "version": distribution.version,
                    "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{distribution.version}",
                    "properties": [
                        {"name": "rasathane:runtime", "value": runtime},
                        {
                            "name": "rasathane:license-metadata",
                            "value": distribution.metadata.get("License-Expression")
                            or distribution.metadata.get("License")
                            or "metadata belirtilmemiş",
                        },
                        {"name": "rasathane:license-files", "value": json.dumps(files)},
                    ],
                }
            )
    # Paket kurulumlarında model dosyalarının lisansı bağımsızdır.
    model_catalog = json.loads(
        (ROOT / "gui/electron/model-catalog.json").read_text(encoding="utf-8-sig")
    )
    for model in model_catalog:
        components.append(
            {
                "type": "data",
                "name": model["repo"],
                "version": model["revision"],
                "hashes": [{"alg": "SHA-256", "content": model["sha256"]}],
                "properties": [
                    {"name": "rasathane:license-metadata", "value": model["license"]},
                    {
                        "name": "rasathane:distribution",
                        "value": "İlk kurulumda kullanıcı indirir; installer içermez",
                    },
                ],
            }
        )
    for name, version, license_name in (
        ("Electron", "43.7.7", "MIT"),
        ("llama.cpp", "b10599-4a08fa297", "MIT"),
        ("Typst", "0.15.1", "Apache-2.0"),
        ("PDF.js", "6.3.289", "Apache-2.0"),
        (
            "akdeniz27/bert-base-turkish-cased-ner",
            "99995f7d2be4b3a28c74f0d36ee97f8c04ee0571",
            "MIT",
        ),
        ("Systran/faster-whisper-small", "536b0662742c02347bc0e980a01041f333bce120", "MIT"),
    ):
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "licenses": [{"license": {"id": license_name}}],
            }
        )
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {"type": "application", "name": "Rasathane", "version": "0.5.0"},
        },
        "components": components,
    }
    (OUTPUT / "SBOM.cdx.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    expected = {
        (OUTPUT / entry["path"]).resolve()
        for component in components
        for prop in component.get("properties", [])
        if prop["name"] == "rasathane:license-files"
        for entry in json.loads(prop["value"])
    }
    # Sadece bu üreticinin iki staging ağacı temizlenir. Upstream source-offer
    # dosyaları ve kullanıcı verisi bu kapsama girmez.
    for runtime in ("sidecar", "worker"):
        generated = (OUTPUT / runtime).resolve()
        generated.relative_to(OUTPUT.resolve())
        for file in generated.rglob("*"):
            if file.is_file() and file.resolve() not in expected:
                file.resolve().relative_to(generated)
                file.unlink()
        for directory in sorted(
            generated.rglob("*"), key=lambda value: len(value.parts), reverse=True
        ):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    obsolete = OUTPUT / "runtime-inventory.json"
    if obsolete.is_file():
        obsolete.unlink()
    print(
        json.dumps(
            {
                "components": len(components),
                "license_files": sum(
                    len(json.loads(prop["value"]))
                    for item in components
                    for prop in item.get("properties", [])
                    if prop["name"] == "rasathane:license-files"
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
