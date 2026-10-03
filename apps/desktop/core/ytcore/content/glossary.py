from __future__ import annotations

import csv
from pathlib import Path

_VARSAYILAN = Path(__file__).parent / "glossary_data" / "hukuk_terimleri.csv"


def glossary_yukle(path: Path) -> list[tuple[str, str]]:
    """CSV (en,tr) → [(kaynak, hedef)]. Başlık satırı + boş/eksik satır atlanır."""
    ciftler: list[tuple[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for satir in csv.reader(f):
            if len(satir) < 2:
                continue
            en, tr = satir[0].strip(), satir[1].strip()
            if not en or not tr or en.lower() == "en":
                continue
            ciftler.append((en, tr))
    return ciftler


def varsayilan_glossary() -> list[tuple[str, str]]:
    """Paketli hukuk terim glossary'si (terim tutarlılığı — A02 LLM kayma azaltma)."""
    return glossary_yukle(_VARSAYILAN)


def glossary_few_shot(glossary: list[tuple[str, str]], limit: int = 30) -> str:
    """Glossary'yi çeviri prompt'una terim kısıtı olarak göm (NMT determinizmine yaklaş)."""
    if not glossary:
        return ""
    satirlar = [f"- {en} → {tr}" for en, tr in glossary[:limit]]
    return "Aşağıdaki terimleri TAM bu karşılıklarla çevir:\n" + "\n".join(satirlar)
