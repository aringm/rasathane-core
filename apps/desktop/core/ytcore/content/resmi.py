"""Resmî Türkçe normatif metinlerde yeniden yazım yerine kaynak alıntıları.

Bu görünüm konsolide mevzuat veya bağımsız hukuki doğrulama üretmez. Edinilen
ana metnin MADDE/fıkra yapısı ve alıntı aralıkları korunur; bağlı ekler takip edilmez.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from ytcore.pipeline.state import GState

MODE = "source_extracts"
SKIP_STATUS = "atlandi_resmi_kaynak"
SKIP_REASON = (
    "Resmî normatif hükümlere genel web aramasıyla doğruluk kararı verilmedi. "
    "Bu görünüm edinilen resmî ana metinden doğrudan alıntılar içerir; "
    "bağımsız doğrulama veya konsolide mevzuat üretimi yapılmadı."
)
_MADDE = re.compile(r"\b(?:GEÇİCİ\s+)?MADDE\s+\d+[A-Z]?\s*[-–—]")
_HEADER = re.compile(
    r"(?P<gun>\d{1,2})\s+(?P<ay>[A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(?P<yil>\d{4})"
    r".*?Resm[îi]\s+Gazete\s+Sayı\s*:\s*(?P<sayi>\d+)",
    re.DOTALL,
)
_MONTHS = {
    "Ocak": 1,
    "Şubat": 2,
    "Mart": 3,
    "Nisan": 4,
    "Mayıs": 5,
    "Haziran": 6,
    "Temmuz": 7,
    "Ağustos": 8,
    "Eylül": 9,
    "Ekim": 10,
    "Kasım": 11,
    "Aralık": 12,
}


@dataclass(frozen=True)
class ResmiMadde:
    baslik: str
    metin: str
    start: int
    end: int


@dataclass(frozen=True)
class ResmiBelge:
    url: str
    bytes_sha256: str
    metin: str
    baslik: str
    giris: str
    yayin_tarihi: str | None
    sayi: str
    sahip: str
    maddeler: tuple[ResmiMadde, ...]
    structure_status: str = "article_quote_boundaries"

    def _kunye(self) -> str:
        return (
            "Doğrudan kaynak alıntıları — metin yeniden yazılmadı.\n\n"
            f"Kaynak: {self.url}\n\n"
            f"Kaynak byte SHA-256: {self.bytes_sha256}\n\n"
            f"{self.giris}"
        )

    def ozet(self) -> dict[str, str]:
        # Seçilmiş TAM cümleler yalnız bir içerik rehberidir. Kesilmiş şart cümlesi
        # veya başkaca maddeden türetilmiş bir hukuki sonuç üretmeyiz.
        girisler = []
        for madde in self.maddeler:
            prefix, quote, _ = madde.metin.partition("“")
            # Yalnız değişiklik bloğundan önceki TAM tanıtım cümlesini seç.
            # 'Belgenin “izin” alanı...' gibi hüküm içi alıntıda maddeyi kesme.
            introduction = bool(quote) and bool(
                re.search(r"(?:değiştirilmiştir|düzenlenmiştir|eklenmiştir)\.\s*$", prefix)
            )
            girisler.append(prefix.strip() if introduction else madde.metin)
        kisa = self._kunye() + "\n\n" + "\n\n".join(girisler[-2:])
        orta = self._kunye() + "\n\n" + "\n\n".join(girisler)
        detay = self._kunye() + "\n\n" + "\n\n".join(m.metin for m in self.maddeler)
        notu = (
            "\n\nKapsam: edinilen ana metin; bağlantılı ekler ayrıca edinilmedi. "
            "MADDE numaraları kaynak belgenindir; alıntılardaki asıl madde ve fıkra "
            "numaraları korunur. Değişikliğin asıl mevzuata uygulanması için bağlı "
            "ekler ve güncel konsolide metin ayrıca incelenmelidir."
        )
        return {"kisa": kisa + notu, "orta": orta + notu, "detay": detay + notu}

    def dokum(self) -> list[dict[str, Any]]:
        return [
            {
                "baslangic_sn": None,
                "baslik": "Kaynak başlığı ve künyesi",
                "metin": self.giris,
                "keywords": [],
            },
            *[
                {
                    "baslangic_sn": None,
                    "baslik": f"Kaynak {m.baslik}",
                    "metin": m.metin,
                    "keywords": [],
                }
                for m in self.maddeler
            ],
        ]

    def provenance(self) -> dict[str, Any]:
        return {
            "method": "direct_source_quotes",
            "primary_source_url": self.url,
            "source_bytes_sha256": self.bytes_sha256,
            "reference_sha256": hashlib.sha256(self.metin.encode("utf-8")).hexdigest(),
            "independent_verification": False,
            "scope": "acquired_main_text_only",
            "attachments_followed": False,
            "structure_status": self.structure_status,
            "excerpts": [
                {
                    "label": m.baslik,
                    "start": m.start,
                    "end": m.end,
                    "sha256": hashlib.sha256(m.metin.encode("utf-8")).hexdigest(),
                }
                for m in self.maddeler
            ],
        }

    def harita(self) -> Any:
        from ytcore.uretim.harita import HaritaDugum

        branches = []
        for index, madde in enumerate(self.maddeler, 1):
            # Fıkra etiketleri doğrudan kaynakta geçen '(8)' gibi işaretlerdir.
            # Bu numaralar yeni bir MADDE diye yorumlanmaz.
            paragraphs = (
                _fikra_sinirlari(madde.metin)
                if self.structure_status == "article_quote_boundaries"
                else []
            )
            leaves = []
            for p_index, paragraph in enumerate(paragraphs):
                end = (
                    paragraphs[p_index + 1].start()
                    if p_index + 1 < len(paragraphs)
                    else len(madde.metin)
                )
                quote = madde.metin[paragraph.start() : end].strip()
                leaves.append(
                    HaritaDugum(
                        id=f"m{index}p{p_index}",
                        label=quote[:120] + ("…" if len(quote) > 120 else ""),
                    )
                )
            branches.append(
                HaritaDugum(id=f"m{index}", label=f"Kaynak {madde.baslik}", cocuklar=leaves)
            )
        label = (
            "Resmî kaynak · MADDE/fıkra rehberi"
            if self.structure_status == "article_quote_boundaries"
            else "Resmî kaynak · ana metin (numaralama ayrımı yapılmadı)"
        )
        return HaritaDugum(id="resmi", label=label, cocuklar=branches)


def _madde_sinirlari(text: str) -> tuple[list[re.Match[str]], bool]:
    """Alıntılanan yeni MADDE, değişiklik düzenlemesinin dış maddesi değildir."""
    candidates = {m.start(): m for m in _MADDE.finditer(text)}
    found = []
    quote_depth = 0
    ascii_quote = False
    malformed = False
    for index, char in enumerate(text):
        if index in candidates and quote_depth == 0 and not ascii_quote:
            found.append(candidates[index])
        if char == "“":
            quote_depth += 1
        elif char == "”":
            if quote_depth == 0:
                malformed = True
            else:
                quote_depth -= 1
        elif char == '"' and quote_depth == 0:
            ascii_quote = not ascii_quote
    return found, quote_depth == 0 and not ascii_quote and not malformed


def _fikra_sinirlari(text: str) -> list[re.Match[str]]:
    """Cümle içi '(2) numaralı fıkra' atfını yeni fıkra diye bölme."""
    found = []
    for marker in re.finditer(r"\((\d+)\)", text):
        suffix = text[marker.end() :].lstrip()
        if re.match(r"(?:numaralı|nolu|no['’]lu|fıkra\w*|bent\w*)\b", suffix, re.I):
            continue
        prefix = text[: marker.start()].rstrip()
        if not prefix or prefix.endswith(("“", '"', "-", "–", "—", ".")):
            found.append(marker)
    return found


def resmi_belge(state: GState) -> ResmiBelge | None:
    """Dar kapı: gerçek RG host, TR, başarılı edinim, byte receipt ve MADDE yapısı."""
    meta = state.get("metadata") or {}
    url = str(meta.get("kaynak_url") or "")
    parsed = urlsplit(url)
    extra = state.get("kaynak_ozel") or {}
    raw_hash = extra.get("source_bytes_sha256")
    text = state.get("icerik_tr") or state.get("transkript_metni") or ""
    if (
        state.get("kaynak_turu") != "web"
        or state.get("kaynak_durumu") != "tam"
        or state.get("transkript_kaynak_dil") != "tr"
        or parsed.scheme != "https"
        or parsed.hostname not in {"www.resmigazete.gov.tr", "resmigazete.gov.tr"}
        or not re.fullmatch(r"/eskiler/\d{4}/\d{2}/\d{8}(?:-\d+)?\.htm", parsed.path)
        or not isinstance(raw_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", raw_hash)
        or "\ufffd" in text
    ):
        return None
    all_matches = list(_MADDE.finditer(text))
    header = _HEADER.search(text[:2000])
    if not all_matches or not header or header.end() > all_matches[0].start():
        return None
    matches, balanced = _madde_sinirlari(text)
    structure_status = "article_quote_boundaries"
    if not balanced or not matches:
        # Belirsiz alıntı sınırında model yoluna geri dönme ve bir hiyerarşi uydurma.
        # Edinilen ana metni aynen tut; yalnız künyeyi ayır.
        first = all_matches[0].start()
        intro = text[:first].strip()
        sections = [
            ResmiMadde("Ana metin (numaralama ayrımı yapılmadı)", text[first:], first, len(text))
        ]
        structure_status = "unbalanced_quotes_raw_text"
    else:
        intro = text[: matches[0].start()].strip()
        sections = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            while end > match.start() and text[end - 1].isspace():
                end -= 1
            sections.append(
                ResmiMadde(
                    match.group().rstrip("-–— "), text[match.start() : end], match.start(), end
                )
            )
    publication = None
    try:
        publication = date(
            int(header["yil"]), _MONTHS[header["ay"]], int(header["gun"])
        ).isoformat()
    except (KeyError, ValueError):
        pass  # Kaynak tarihini tahmin etme; alıntı künyesi yine aynen korunur.
    authority_match = re.search(r"(?:YÖNETMELİK|TEBLİĞ|KARAR)\s+(.{3,150}?)ndan:\s*", intro)
    authority = authority_match[1] if authority_match else "Resmî Gazete"
    title = (
        intro[authority_match.end() :].strip() if authority_match else intro[header.end() :].strip()
    )
    return ResmiBelge(
        url,
        raw_hash,
        text,
        title,
        intro,
        publication,
        header["sayi"],
        authority,
        tuple(sections),
        structure_status,
    )
