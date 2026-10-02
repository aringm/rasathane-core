from __future__ import annotations

from ytcore.models import IndexKaydi
from ytcore.output.transcript_yaz import transcript_yaz


def _kayit():
    return IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="Test Başlık",
        anadil="tr",
        kanal="Kanal",
        yayin_tarihi="2026-01-15",
        sure_sn=642,
        konu="hukuk",
        uretici_slug="kanal",
        video_slug="test-baslik",
        analiz_tarihi="2026-06-07",
    )


def test_altyazi_transkript_yazilir(tmp_path):
    transcript_yaz(tmp_path, _kayit(), "Merhaba dünya.", "altyazi", None)
    p = tmp_path / "01_transcript_orijinal.md"
    assert p.exists()
    icerik = p.read_text(encoding="utf-8")
    assert "Merhaba dünya." in icerik
    assert "Av. Mehmet Arın Gülüm" in icerik
    assert "Test Başlık" in icerik


def test_altyazi_yok_not_duser(tmp_path):
    transcript_yaz(tmp_path, _kayit(), "", "altyazi_yok", None)
    icerik = (tmp_path / "01_transcript_orijinal.md").read_text(encoding="utf-8")
    assert "asr_izin" in icerik or "altyazı bulunamadı" in icerik.lower()


def test_asr_kaynak_etiketi(tmp_path):
    transcript_yaz(tmp_path, _kayit(), "asr metni", "asr", "whisperx")
    icerik = (tmp_path / "01_transcript_orijinal.md").read_text(encoding="utf-8")
    assert "whisperx" in icerik.lower()
    assert "asr metni" in icerik


def test_altyazi_durumu_bos_metinle_celismez(tmp_path):
    # Review HIGH/MED: durum='altyazi' artık boş metinle gelmez; ama gelse bile belge
    # KENDİSİYLE çelişmemeli. 'altyazi' etiketi + dolu gövde tutarlı.
    transcript_yaz(tmp_path, _kayit(), "gerçek metin", "altyazi", None)
    icerik = (tmp_path / "01_transcript_orijinal.md").read_text(encoding="utf-8")
    assert "Altyazı (yt-dlp)" in icerik and "gerçek metin" in icerik
    assert "altyazı bulunamadı" not in icerik.lower()  # çelişki yok


def test_icerik_bos_durumu(tmp_path):
    transcript_yaz(tmp_path, _kayit(), "", "icerik_bos", "whisperx")
    icerik = (tmp_path / "01_transcript_orijinal.md").read_text(encoding="utf-8")
    assert "konuşma" in icerik.lower() and "whisperx" in icerik.lower()


def test_hata_durumu_not_duser(tmp_path):
    transcript_yaz(tmp_path, _kayit(), "", "hata", None, hata="DownloadError: private video")
    icerik = (tmp_path / "01_transcript_orijinal.md").read_text(encoding="utf-8")
    assert "erişile" in icerik.lower() and "DownloadError" in icerik
