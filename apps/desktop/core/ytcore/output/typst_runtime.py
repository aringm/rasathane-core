"""PDF için paketli Typst; geliştirmede mevcut PATH sözleşmesi korunur."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def typst_executable() -> Path:
    configured = os.environ.get("RASATHANE_TYPST_BIN", "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            raise ValueError("PDF motorunun path ayarı geçersiz.")
        if not path.is_file():
            raise FileNotFoundError("PDF motoru bu kurulumda bulunamadı.")
        return path.resolve()
    if getattr(sys, "frozen", False):
        raise FileNotFoundError("PDF motoru bu kurulumda bulunamadı.")
    executable = shutil.which("typst")
    if executable is None:
        raise FileNotFoundError("PDF motoru geliştirme ortamında bulunamadı.")
    return Path(executable).resolve()


def compile_pdf(source: Path, target: Path) -> Path:
    """Doğrulanmış PDF'yi atomik teslim eder; boş/stale çıktı başarı sayılmaz."""
    executable = typst_executable()
    source, target = source.resolve(), target.resolve()
    if source.parent != target.parent or target.suffix.casefold() != ".pdf":
        raise ValueError("PDF çıktı konumu geçersiz.")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.stem}-", suffix=".partial.pdf", dir=source.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        try:
            subprocess.run(
                [
                    str(executable),
                    "compile",
                    "--root",
                    str(source.parent),
                    str(source),
                    str(temporary),
                ],
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=180,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("PDF üretimi zaman aşımına uğradı.") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("PDF motoru belgeyi derleyemedi.") from exc
        with temporary.open("rb") as output:
            if output.read(5) != b"%PDF-" or temporary.stat().st_size < 8:
                raise RuntimeError("PDF motoru geçerli bir PDF çıktısı üretmedi.")
        temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)
