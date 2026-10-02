from __future__ import annotations

from ytcore.transcript.vtt import temizle_vtt, vtt_segmentler


def test_vtt_segmentler_zaman_damgali():
    vtt = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nBirinci cümle.\n\n"
        "00:01:05.000 --> 00:01:08.000\nİkinci cümle.\n"
    )
    segs = vtt_segmentler(vtt)
    assert len(segs) == 2
    assert segs[0]["baslangic_sn"] == 1
    assert segs[1]["baslangic_sn"] == 65
    assert "Birinci" in segs[0]["metin"]


def test_vtt_segmentler_html_strip():
    vtt = "WEBVTT\n\n00:00:02.000 --> 00:00:05.000\n<c>Etiketli</c> metin.\n"
    segs = vtt_segmentler(vtt)
    assert segs[0]["metin"] == "Etiketli metin."


def test_vtt_segmentler_bos():
    assert vtt_segmentler("WEBVTT\n\n") == []


VTT = """WEBVTT
Kind: captions
Language: tr

00:00:01.000 --> 00:00:03.000
Merhaba <c>dünya</c>

00:00:03.000 --> 00:00:05.000
Merhaba dünya

00:00:05.000 --> 00:00:07.000
bugün hava güzel
"""


def test_header_ve_timestamp_silinir():
    t = temizle_vtt(VTT)
    assert "WEBVTT" not in t and "-->" not in t and "Kind:" not in t


def test_html_tag_strip():
    t = temizle_vtt(VTT)
    assert "<c>" not in t and "dünya" in t


def test_ardisik_dedup():
    # "Merhaba dünya" iki ardışık cue'da → tek kez
    assert temizle_vtt(VTT).count("Merhaba dünya") == 1


def test_icerik_korunur():
    assert "bugün hava güzel" in temizle_vtt(VTT)


def test_bos_girdi():
    assert temizle_vtt("") == ""


def test_zaman_damgali_inline_satir():
    # bazı auto-sub'larda inline <00:00:01.500> timestamp tag'leri olur
    v = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<00:00:01.500>kelime<00:00:01.800>"
    t = temizle_vtt(v)
    assert "00:00:01.500" not in t and "kelime" in t


def test_srt_index_atlanir():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nilk satır\n\n2\n00:00:02,000 --> 00:00:03,000\nikinci"
    t = temizle_vtt(srt)
    assert "ilk satır" in t and "ikinci" in t and t.strip()[0] != "1"
