from __future__ import annotations

from ytcore.router.complexity import Hedef, Karmasiklik, siniflandir, yonlendir


def test_pii_hard_override_local():
    k = yonlendir(karmasiklik=Karmasiklik.COMPLEX, pii_var=True)
    assert k.hedef == Hedef.LOCAL  # PII -> her zaman local


def test_simple_local():
    assert yonlendir(Karmasiklik.SIMPLE, pii_var=False).hedef == Hedef.LOCAL


def test_complex_pii_temiz_cloud():
    assert yonlendir(Karmasiklik.COMPLEX, pii_var=False).hedef == Hedef.CLOUD


def test_cloud_erisilemez_graceful_local():
    assert (
        yonlendir(Karmasiklik.COMPLEX, pii_var=False, cloud_erisilebilir=False).hedef == Hedef.LOCAL
    )


# --- Faz 5: gerçek complexity sınıflandırma (heuristik, A11) ---


def test_siniflandir_selamlama_simple():
    assert siniflandir("Merhaba, bu video güzeldi.") == Karmasiklik.SIMPLE


def test_siniflandir_muhakeme_complex():
    metin = (
        "Bu kararı değerlendir: gerekçedeki çelişki neden önemli? İki içtihadı karşılaştır "
        "ve hangi stratejinin üstün olduğunu adım adım analiz et. " * 30
    )
    assert siniflandir(metin) == Karmasiklik.COMPLEX


def test_siniflandir_buyuk_harf_turkce_i_tuzagi():
    # 'İ'.lower() combining-dot tuzağı (Faz 2/4 dersi): BÜYÜK yazılmış işaretler kaçmamalı.
    metin = (
        "BU KARARI DEĞERLENDİR: ÇELİŞKİ NEDEN ÖNEMLİ? İÇTİHATLARI KARŞILAŞTIR VE ANALİZ ET. " * 30
    )
    assert siniflandir(metin) == Karmasiklik.COMPLEX


def test_siniflandir_uzun_ama_duz_metin_medium():
    metin = "Video bahçe düzenlemesini anlatıyor. " * 900  # uzun ama muhakeme işareti yok
    assert siniflandir(metin) == Karmasiklik.MEDIUM


def test_siniflandir_ayirt_edici():
    # Eval-moat disiplini: metrik totolojik değil — muhakeme > selamlama sıralaması.
    basit = siniflandir("Selam!")
    derin = siniflandir("Neden bu tez çelişkili? Karşılaştır, değerlendir, analiz et. " * 50)
    assert (basit, derin) == (Karmasiklik.SIMPLE, Karmasiklik.COMPLEX)


def test_siniflandir_esik_env_override(monkeypatch):
    # TR korpus gelince kalibrasyon env üzerinden (eşik KİLİTLİ DEĞİL — değişmez #3).
    monkeypatch.setenv("YT_COMPLEXITY_ESIK", "99")
    metin = "Neden bu tez çelişkili? Karşılaştır, değerlendir, analiz et."
    assert siniflandir(metin) != Karmasiklik.COMPLEX


def test_siniflandir_yalniz_i_isaretleri_buyuk_metin():
    # review tur-1 MED: 'KARSILASTIR'.lower()='karsilastir' (I->i) 'karsilastir'(i-noktasiz)
    # ile eslesmez -> yalniz-i iceren isaretler ('karsilastir','kanitla','adim adim') BUYUK
    # metinde olurdu. I->i katlamasi lower'dan ONCE yapilmali.
    metin = "KARŞILAŞTIR VE KANITLA: BU TEZİ ADIM ADIM İNCELE. " * 40
    assert siniflandir(metin) == Karmasiklik.COMPLEX
