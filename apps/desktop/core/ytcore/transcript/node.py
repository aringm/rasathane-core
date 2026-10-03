from __future__ import annotations

import tempfile
from pathlib import Path

from ytcore.errors import KOD_HATALARI
from ytcore.models import TranskriptSonuc
from ytcore.transcript.asr import ASRWorker
from ytcore.transcript.fetcher import Fetcher
from ytcore.transcript.vtt import temizle_vtt, vtt_segmentler


def transkript_uret(
    fetcher: Fetcher, url: str, asr_izin: bool, asr: ASRWorker | None
) -> TranskriptSonuc:
    """Altyazı-önce; altyazı yoksa/boşsa & asr_izin ise ASR; aksi altyazi_yok.

    DoD sözleşmesi: SESSİZ başarı/başarısızlık YOK.
    - Altyazı var ama temizlenince BOŞ (yalnız müzik/sessizlik/header cue'ları) →
      kullanılabilir altyazı yok say (sessiz boş-transkript "başarı" üretme).
    - ASR çalışır ama konuşma çıkaramazsa → durum="icerik_bos" (sessiz boş değil).
    - Altyazı yoksa & asr_izin yoksa → durum="altyazi_yok" (kullanıcıya sor).
    """
    alt = fetcher.altyazi(url)
    metin = temizle_vtt(alt.vtt).strip() if alt is not None else ""
    if metin:
        # Zaman-damgalı segmentler (Faz 2 kronolojik döküm timestamp kaynağı) — VTT
        # cue'larından. Saf parse: GERÇEK kod-bug re-raise (timestamp'i sessizce kaybetme),
        # yalnız bozuk-altyazı-verisi sınırında boş düş (metni kaybetme).
        try:
            timed = vtt_segmentler(alt.vtt) if alt is not None else []
        except KOD_HATALARI:
            raise
        except Exception:  # noqa: BLE001 — bozuk VTT verisi; timestamp best-effort
            timed = []
        return TranskriptSonuc(
            metin=metin,
            durum="altyazi",
            kaynak_dil=alt.dil if alt else None,
            segment_sayisi=metin.count(". ") + 1,
            segmentler=timed,
        )
    # Buraya kadar: kullanılabilir altyazı YOK (hiç yok ya da boş-temizlendi).
    if not asr_izin or asr is None:
        return TranskriptSonuc(metin="", durum="altyazi_yok", kaynak_dil=None)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        # ignore_cleanup_errors: taze WAV'a AV/indexer geçici kilidi (Faz 0 Windows dersi)
        # ASR başarıyla bittikten sonra teardown'ı çökertmesin.
        ses = fetcher.ses_indir(url, Path(d))
        r = asr.calistir(ses, dil="tr", diarize=False)
    asr_metin = (r.metin or "").strip()
    if not asr_metin:
        # ASR koştu ama konuşma yok (sessiz/müzik) — sessiz boş "asr" başarısı verme.
        return TranskriptSonuc(metin="", durum="icerik_bos", kaynak_dil=r.dil, asr_tier=r.tier)
    return TranskriptSonuc(
        metin=asr_metin,
        durum="asr",
        kaynak_dil=r.dil,
        segment_sayisi=r.segment_sayisi,
        asr_tier=r.tier,
    )
