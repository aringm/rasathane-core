from __future__ import annotations

from pathlib import Path

import pytest
from ytcore.transcript.asr import ASRSonuc
from ytcore.transcript.fetcher import FixtureFetcher
from ytcore.transcript.node import transkript_uret


def test_timed_parse_kod_bug_reraise(monkeypatch):
    # Saf VTT-parse'taki GERÇEK kod-bug timestamp'i sessizce kaybetmemeli → re-raise
    from ytcore.transcript import node as node_mod

    def patlat(_icerik):
        raise KeyError("regex grubu degisti")

    monkeypatch.setattr(node_mod, "vtt_segmentler", patlat)
    with pytest.raises(KeyError):
        transkript_uret(FixtureFetcher("clean"), "u", asr_izin=False, asr=None)


def test_altyazi_yolu_temiz_metin():
    t = transkript_uret(FixtureFetcher("clean"), "https://youtu.be/x", asr_izin=False, asr=None)
    assert t.durum == "altyazi" and "sözleşme" in t.metin.lower()
    assert "-->" not in t.metin and t.kaynak_dil == "tr"


def test_altyazi_yok_asr_izinsiz_sormali():
    t = transkript_uret(
        FixtureFetcher("altyazi_yok"), "https://youtu.be/x", asr_izin=False, asr=None
    )
    assert t.durum == "altyazi_yok" and t.metin == ""  # SESSİZ ASR YOK


class _FakeASR:
    def calistir(self, ses: Path, dil: str, diarize: bool) -> ASRSonuc:
        return ASRSonuc(metin="asr metni", segment_sayisi=3, dil="tr", tier="whisperx")


class _SesliFetcher(FixtureFetcher):
    def ses_indir(self, url: str, hedef_dir: Path) -> Path:
        p = hedef_dir / "s.wav"
        p.write_bytes(b"x")
        return p


def test_altyazi_yok_asr_izinli_fake_worker():
    t = transkript_uret(
        _SesliFetcher("altyazi_yok"), "https://youtu.be/x", asr_izin=True, asr=_FakeASR()
    )
    assert t.durum == "asr" and t.metin == "asr metni" and t.asr_tier == "whisperx"
    assert t.segment_sayisi == 3


class _BosASR:
    def calistir(self, ses: Path, dil: str, diarize: bool) -> ASRSonuc:
        return ASRSonuc(metin="   ", segment_sayisi=0, dil="tr", tier="whisperx")


def test_bos_temizlenen_altyazi_basari_sayilmaz():
    # Review HIGH: track var ama temizlenince boş → durum="altyazi" + boş metin OLMAMALI.
    t = transkript_uret(FixtureFetcher("bos"), "https://youtu.be/x", asr_izin=False, asr=None)
    assert t.durum == "altyazi_yok" and t.metin == ""  # sessiz boş-transkript YOK


def test_bos_altyazi_asr_izinli_ase_duser():
    # Boş altyazı + asr_izin → ASR denenir (kullanılabilir altyazı yok sayılır).
    t = transkript_uret(_SesliFetcher("bos"), "https://youtu.be/x", asr_izin=True, asr=_FakeASR())
    assert t.durum == "asr" and t.metin == "asr metni"


def test_asr_bos_cikti_icerik_bos():
    # Review HIGH: ASR koştu ama konuşma yok → durum="icerik_bos" (sessiz "asr" başarısı YOK).
    t = transkript_uret(
        _SesliFetcher("altyazi_yok"), "https://youtu.be/x", asr_izin=True, asr=_BosASR()
    )
    assert t.durum == "icerik_bos" and t.metin == "" and t.asr_tier == "whisperx"
