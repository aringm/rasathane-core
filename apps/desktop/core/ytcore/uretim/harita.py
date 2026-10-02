from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field

from ytcore.content.llm import LLMClient

_SISTEM = (
    "Sen bir içerik analistisin. Verilen Türkçe içeriği derin ve hiyerarşik bir zihin haritası "
    "ağacına dönüştür. Yalnızca geçerli JSON döndür (açıklama veya markdown ekleme), şu iç içe "
    "şemada: "
    '{"label":"kök başlık","cocuklar":[{"label":"ana dal","cocuklar":'
    '[{"label":"alt dal","cocuklar":[{"label":"detay","cocuklar":[]}]}]}]}. '
    "Derinlik zorunludur: en az 3, tercihen 4 seviye (kök → ana dal → alt dal → yaprak detay). "
    "Kök altında 4-7 ana dal bulunmalı; her ana dalın 2-5 alt dalı olmalı; önemli alt dalların "
    "1-3 yaprak detayı eklenmeli. Düz, tek seviyeli (yalnızca ana dal içeren) ağaç kabul edilmez. "
    "Her etiket kısa (en fazla 8 kelime) ve Türkçe olmalı. Yalnız içerikte geçen kavramları "
    "kullan; bilgi uydurma."
)
_LABEL_CAP = 120


@dataclass
class HaritaDugum:
    id: str
    label: str
    cocuklar: list[HaritaDugum] = field(default_factory=list)
    zaman_sn: int | None = None


def _json_cikar(ham: str) -> dict[str, object]:
    """LLM çıktısından ilk JSON nesnesini çıkar (```json fence veya ham ilk{...}).

    raw_decode ilk TAM JSON objesini parse eder → JSON sonrası açıklama metni ('}' içerse
    bile) yutulmaz (rfind('}') tuzağı yok: 'review tur-1 HIGH'). object_pairs gerekmiyor."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", ham, re.DOTALL)
    aday = m.group(1) if m else ham
    b = aday.find("{")
    if b == -1:
        raise ValueError("JSON bulunamadı")
    veri, _son = json.JSONDecoder().raw_decode(aday, b)
    if not isinstance(veri, dict):
        raise ValueError("JSON nesne değil")
    return veri


def _dict_to_dugum(d: dict[str, object], sayac: list[int]) -> HaritaDugum:
    sayac[0] += 1
    label = str(d.get("label", "")).strip() or "(başlıksız)"
    zaman = d.get("zaman_sn")
    cocuk_ham = d.get("cocuklar") or []
    cocuklar = (
        [_dict_to_dugum(c, sayac) for c in cocuk_ham if isinstance(c, dict)]
        if isinstance(cocuk_ham, list)
        else []
    )
    # bool, int alt-tipidir → açıkça ayır (True'yu zaman_sn=1 sayma); isinstance daraltır.
    zaman_sn: int | None = None
    if isinstance(zaman, (int, float)) and not isinstance(zaman, bool):
        zaman_sn = int(zaman)
    return HaritaDugum(
        id=f"n{sayac[0]}",
        label=label[:_LABEL_CAP],
        zaman_sn=zaman_sn,
        cocuklar=cocuklar,
    )


def harita_agaci(govde: str, llm: LLMClient, *, model: str | None = None) -> HaritaDugum:
    """İçerikten zihin haritası ağacı (LLM→JSON). Geçersiz JSON → graceful tek-düğüm kök
    (ilk cümle; sessiz boş değil — çağıran dugum_say==1 ile 'icerik_yok' ayırt eder)."""
    if not govde.strip():
        return HaritaDugum(id="n1", label="(içerik yok)")
    ham = llm.uret(_SISTEM, govde[:8000], model=model)  # derin ağaç için daha geniş bağlam
    try:
        veri = _json_cikar(ham)
    except (ValueError, json.JSONDecodeError):
        ilk = (govde.strip().split(".")[0] or "İçerik").strip()[:80]
        return HaritaDugum(id="n1", label=ilk)
    return _dict_to_dugum(veri, [0])


def agac_to_markmap(agac: HaritaDugum, *, video_url: str = "") -> dict[str, object]:
    """HaritaDugum → markmap veri-ağacı {content, children}. content = HTML-escape'li label;
    zaman_sn varsa YouTube &t=Ns citation link'i eklenir (düğüm→kaynak→zaman = NotebookLM farkı)."""
    icerik = html.escape(agac.label)
    if agac.zaman_sn is not None and video_url:
        ayrac = "&" if "?" in video_url else "?"
        url = html.escape(f"{video_url}{ayrac}t={agac.zaman_sn}s")
        icerik += f' <a href="{url}">⏱{agac.zaman_sn}s</a>'
    return {
        "content": icerik,
        "children": [agac_to_markmap(c, video_url=video_url) for c in agac.cocuklar],
    }


def dugum_say(agac: HaritaDugum) -> int:
    return 1 + sum(dugum_say(c) for c in agac.cocuklar)
