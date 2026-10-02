from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class FetchMeta:
    info: dict[str, Any]


@dataclass
class AltyaziSonuc:
    vtt: str
    dil: str


class Fetcher(Protocol):
    def metadata(self, url: str) -> FetchMeta: ...
    def altyazi(self, url: str) -> AltyaziSonuc | None: ...
    def ses_indir(self, url: str, hedef_dir: Path) -> Path: ...


_CLEAN_VTT = """WEBVTT
Kind: captions
Language: tr

00:00:01.000 --> 00:00:04.000
Bugün sözleşme hukukunun temel ilkelerini konuşacağız.

00:00:04.000 --> 00:00:07.000
İrade serbestisi modern borçlar hukukunun çekirdeğidir.
"""

# Konuşulan TCKN benzeri 11 haneli blok → pii_gate tetikler (fail-closed kanıtı)
_PII_VTT = """WEBVTT
Language: tr

00:00:01.000 --> 00:00:03.000
Müvekkilin kimlik numarası 12345678950 olarak kayıtlı.
"""

# Altyazı track'i VAR ama temizlenince BOŞ (yalnız header/timestamp — müzik/sessizlik)
_BOS_VTT = """WEBVTT
Kind: captions
Language: tr

00:00:01.000 --> 00:00:03.000

00:00:03.000 --> 00:00:05.000
"""

_FIX_META: dict[str, Any] = {
    "id": "fixtureID01",
    "title": "Sözleşme Hukuku Söyleşisi",
    "channel": "Hukuk Kanalı",
    "uploader": "Hukuk Kanalı",
    "upload_date": "20260115",
    "duration": 420,
    "webpage_url": "https://youtu.be/fixtureID01",
    "language": "tr",
}


class FixtureFetcher:
    """Ağsız deterministik fetcher (test + frozen-exe selftest).

    mod: "clean" | "pii" | "altyazi_yok" | "bos" | "hata" | <vtt-dosya-yolu>. Frozen exe
    içine kod inject edilemez ama YT_TRANSCRIPT_FIXTURE env set edilebilir → selftest
    bununla tüm kablolama'yı (klasör+index+transcript+0 cloud) ağsız/torch'suz doğrular.
    """

    def __init__(self, mod: str) -> None:
        self.mod = mod

    def metadata(self, url: str) -> FetchMeta:
        if self.mod == "hata":  # ağ/erişim hatası simülasyonu (graceful surface testi)
            raise RuntimeError("video erişilemedi (simüle)")
        if self.mod == "kod_bug":  # iç kod hatası simülasyonu (re-raise testi, R4)
            raise AttributeError("'NoneType' object has no attribute 'get'")
        info = {**_FIX_META, "webpage_url": url}
        if self.mod == "na":  # canlı/kısıtlı video: duration='NA' (R1 regresyon)
            info["duration"] = "NA"
        return FetchMeta(info=info)

    def altyazi(self, url: str) -> AltyaziSonuc | None:
        if self.mod in ("altyazi_yok", "hata"):
            return None
        if self.mod == "na":  # NA-duration ama altyazı VAR → transkript kaybolmamalı
            return AltyaziSonuc(vtt=_CLEAN_VTT, dil="tr")
        if self.mod == "pii":
            return AltyaziSonuc(vtt=_PII_VTT, dil="tr")
        if self.mod == "bos":  # track var ama temizlenince boş (sessiz boş-transkript testi)
            return AltyaziSonuc(vtt=_BOS_VTT, dil="tr")
        if self.mod == "clean":
            return AltyaziSonuc(vtt=_CLEAN_VTT, dil="tr")
        p = Path(self.mod)
        if p.is_file():
            return AltyaziSonuc(vtt=p.read_text(encoding="utf-8"), dil="tr")
        return AltyaziSonuc(vtt=_CLEAN_VTT, dil="tr")

    def ses_indir(self, url: str, hedef_dir: Path) -> Path:
        # Fixture modunda gerçek ses yok; ASR yolu testleri fake ASRWorker kullanır.
        raise RuntimeError("FixtureFetcher ses indirmez (ASR testleri fake worker kullanır)")


def fetcher_al() -> Fetcher:
    """env YT_TRANSCRIPT_FIXTURE set ise FixtureFetcher, değilse gerçek YtDlpFetcher."""
    fix = os.environ.get("YT_TRANSCRIPT_FIXTURE", "").strip()
    if fix:
        return FixtureFetcher(fix)
    from ytcore.transcript.ytdlp_fetcher import YtDlpFetcher  # lazy: yt-dlp ağır import

    return YtDlpFetcher()
