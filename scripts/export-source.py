"""Denetlenecek açık kaynak export'u; özel Git geçmişi ve runtime taşınmaz."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = ("apps/desktop/core/", "apps/desktop/mcp/", "apps/desktop/tests/", "apps/desktop/eval/",
           "apps/desktop/gui/electron/", "apps/desktop/gui/scripts/", "apps/desktop/gui/ui/", "apps/desktop/gui/src-tauri/icons/",
           "apps/desktop/gui/src-tauri/src/", "apps/desktop/gui/src-tauri/capabilities/",
           "apps/desktop/infra/", "apps/radar/apps/", "apps/radar/packages/", "apps/radar/tests/",
           "apps/radar/alembic/", "apps/web/src/", "apps/web/public/", "apps/web/scripts/", "docs/urun/", "scripts/", ".github/")
ROOT_FILES = {"LICENSE", "NOTICE.md", "README.md", "CONTRIBUTING.md", ".gitignore", ".gitattributes", "AGENTS.md",
              "apps/desktop/pyproject.toml", "apps/desktop/uv.lock", "apps/desktop/LICENSE", "apps/desktop/.env.example", "apps/desktop/.gitignore",
              "apps/desktop/gui/package.json", "apps/desktop/gui/pnpm-lock.yaml", "apps/desktop/gui/pnpm-workspace.yaml",
              "apps/desktop/gui/src-tauri/tauri.conf.json", "apps/desktop/gui/src-tauri/Cargo.toml",
              "apps/desktop/gui/src-tauri/Cargo.lock", "apps/desktop/gui/src-tauri/build.rs",
              "apps/radar/pyproject.toml", "apps/radar/uv.lock", "apps/radar/alembic.ini", "apps/radar/.env.example",
              "apps/web/package.json", "apps/web/pnpm-lock.yaml", "apps/web/pnpm-workspace.yaml", "apps/web/next.config.ts", "apps/web/AGENTS.md",
              "apps/web/tsconfig.json", "apps/web/postcss.config.mjs", "apps/web/eslint.config.mjs"}
FORBIDDEN_PARTS = {".venv", "node_modules", "vendor", "dist", "worker-build", "worker-dist", "build", ".local", "__pycache__"}
PDF_MODULES = {
    "apps/desktop/gui/ui/lib/pdfjs/build/pdf.mjs",
    "apps/desktop/gui/ui/lib/pdfjs/build/pdf.worker.mjs",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--public", action="store_true", help="AGENTS Git rehberini açık depo için uyarla")
    args = parser.parse_args()
    destination = args.destination.resolve()
    destination.relative_to(ROOT / ".local")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Export hedefi boş olmalı; mevcut dosyalar silinmez.")
    paths = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                           cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
    records = []
    for relative in sorted(set(paths)):
        file = ROOT / relative
        if not relative or not file.is_file() or (relative not in ROOT_FILES and not relative.startswith(ALLOWED)):
            continue
        blocked = FORBIDDEN_PARTS.intersection(Path(relative).parts)
        if relative in PDF_MODULES:
            blocked.discard("build")
        if blocked or file.suffix.lower() in {".exe", ".zip", ".gguf", ".sqlite", ".db", ".log", ".spec"}:
            continue
        if file.name.startswith(".env") and file.name != ".env.example":
            continue
        file.resolve().relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        source_sha256 = hashlib.sha256(file.read_bytes()).hexdigest()
        if args.public and relative == "AGENTS.md":
            content = target.read_text(encoding="utf-8")
            content = content.replace(
                "- `docs/birlestirme`: kaynak envanteri, koruma kaydı, ürün/tasarım birleştirme planı.",
                "- `docs/urun`: ürün planı, mimari, doğrulama ve yayın kayıtları. Yerel/özel envanter açık export'a alınmaz.",
            ).replace(
                "- Ana remote `aringm/rasathane-gozlemevi`; mevcut default branch `master`.",
                "- Ana remote `aringm/rasathane-core`; default branch `main`.",
            ).replace(
                "- Kaynak geçmişleri subtree ile, squash olmadan içeri alınmıştır. `sources/*` dalları ve `source-*` tag'leri özgün ağaçları korur.",
                "- Özgün kaynak geçmişleri private çalışma deposunda subtree, `sources/*` ve `source-*` ref'leriyle korunur. Bu açık repo yalnız denetlenmiş source export'u içerir; özel geçmişi taşımaz.",
            ).replace(
                "- Geçmişteki kaynak ağacı `git archive <source-tag>` ile geri alınabilir. Subtree klasöründen eski repoya push için `git subtree split --prefix=apps/<ad>` kullanılır.",
                "- Kaynak kökeni SOURCE-MANIFEST.json ile izlenir. Özel kaynak ref'leri bu açık depoda bulunmaz. Değişiklikler feature branch ve PR üzerinden yapılır.",
            )
            target.write_text(content, encoding="utf-8")
        records.append({"path": relative, "source_sha256": source_sha256, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bytes": target.stat().st_size})
    (destination / "SOURCE-MANIFEST.json").write_text(json.dumps({"files": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"files": len(records), "bytes": sum(row["bytes"] for row in records), "destination": str(destination)}))


if __name__ == "__main__":
    main()
