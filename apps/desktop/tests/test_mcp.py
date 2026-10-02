from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

from fastmcp import Client
from ytmcp.server import mcp


async def test_health_tool():
    async with Client(mcp) as c:
        r = await c.call_tool("health", {})
        assert r.data["durum"] == "ok"


async def test_health_faz5():
    async with Client(mcp) as c:
        r = await c.call_tool("health", {})
        assert r.data["faz"] == 5


async def test_analiz_et_tool(tmp_output_base, tmp_path, monkeypatch):
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("YT_FORCE_COMPLEX", "0")
    async with Client(mcp) as c:
        r = await c.call_tool("analiz_et", {"url": "https://youtu.be/abc", "konu": "genel"})
        # Faz 1: fixture-clean altyazı → gerçek transkript (stub=False)
        assert r.data["stub"] is False
        assert r.data["transkript_durumu"] == "altyazi"
        assert r.data["cloud_cagrisi_sayisi"] == 0


async def test_kaynak_analiz_et_tool_github(tmp_output_base, tmp_path, monkeypatch):
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("RASATHANE_SOURCE_FIXTURE", "1")
    async with Client(mcp) as c:
        r = await c.call_tool(
            "kaynak_analiz_et",
            {"url": "https://github.com/openai/openai-python", "konu": "genel"},
        )
        assert r.data["stub"] is False
        assert r.data["kaynak_turu"] == "github"
        assert r.data["transkript_durumu"] == "kaynak"


# --- Faz 5: tam adım-tool yüzeyi (Mod A — host LLM zincirler; senkron+stateless+JSON) ---


async def test_faz5_adim_toollari_listede():
    async with Client(mcp) as c:
        adlar = {t.name for t in await c.list_tools()}
        assert {
            "health",
            "analiz_et",
            "kaynak_analiz_et",
            "transcript_al",
            "cevir",
            "ozetle",
            "dokum_cikar",
            "degerlendir",
            "fact_check",
            "zihin_haritasi",
            "seslendir",
            "indeks_ara",
            "kurulum_kontrol",
            "ses_modeli_indir",
        } <= adlar


async def test_cevir_tool():
    async with Client(mcp) as c:
        r = await c.call_tool("cevir", {"metin": "The court ruled in favor of the plaintiff."})
        assert r.data["durum"] == "cevrildi" and r.data["icerik_tr"].strip()


async def test_ozetle_tool():
    async with Client(mcp) as c:
        r = await c.call_tool(
            "ozetle", {"metin": "Video yapay zekâ düzenlemelerini anlatıyor. " * 40}
        )
        assert r.data["detay"].strip()


async def test_zihin_haritasi_tool_json_agac():
    async with Client(mcp) as c:
        r = await c.call_tool(
            "zihin_haritasi", {"metin": "Yapay zekâ düzenlemeleri ve etik. " * 30}
        )
        assert r.data["dugum_sayisi"] >= 1 and "agac" in r.data
        assert "html" not in r.data  # 400KB vendored-JS şişmesi YOK (tasarım kararı)


async def test_seslendir_tool(tmp_path, tmp_output_base):
    async with Client(mcp) as c:
        hedef = str(tmp_path / "out.wav")
        r = await c.call_tool("seslendir", {"metin": "Kısa özet metni.", "hedef_dosya": hedef})
        assert r.data["durum"] == "uretildi" and r.data["kaynak"] == "fake"  # YT_TTS_FIXTURE


async def test_fact_check_tool():
    async with Client(mcp) as c:
        r = await c.call_tool("fact_check", {"metin": "Türkiye 2023'te genel seçim yaptı."})
        assert r.data["durum"] in ("uretildi", "web_yok", "web_hata", "icerik_yok")


async def test_indeks_ara_tool(tmp_output_base):
    async with Client(mcp) as c:
        r = await c.call_tool("indeks_ara", {"sorgu": "yapay zekâ", "k": 3})
        assert "sonuclar" in r.data  # boş korpus → boş liste (hata değil)


async def test_kurulum_kontrol_tool(tmp_output_base):
    async with Client(mcp) as c:
        r = await c.call_tool("kurulum_kontrol", {})
        for alan in (
            "ollama_erisilebilir",
            "piper_voice_hazir",
            "anthropic_anahtar_var",
            "cloud_verdict_acik",
        ):
            assert alan in r.data


# --- review tur-1 fixleri: bos != basari MCP tool'larinda da (pipeline ile ayni disiplin) ---


async def test_degerlendir_bos_metin_sahte_puan_yok(tmp_output_base):
    # review tur-1 HIGH: bos metin sogus-baslangic faktorlerinden 65.0 "puan" almamali.
    async with Client(mcp) as c:
        r = await c.call_tool("degerlendir", {"metin": "   "})
        assert r.data["puan"] is None and r.data["durum"] == "icerik_yok"


async def test_ozetle_bos_metin_durum(tmp_output_base):
    async with Client(mcp) as c:
        r = await c.call_tool("ozetle", {"metin": ""})
        assert r.data["durum"] == "icerik_yok"


async def test_dokum_bos_metin_durum(tmp_output_base):
    async with Client(mcp) as c:
        r = await c.call_tool("dokum_cikar", {"metin": ""})
        assert r.data["durum"] == "icerik_yok" and r.data["bolumler"] == []


async def test_zihin_haritasi_bos_metin_dejenere_agac(tmp_output_base, tmp_path):
    # Pipeline harita_node dugum_say<=1'i icerik_yok sayar — tool da saymali; dejenere
    # agacta HTML dosyasi da YAZILMAMALI.
    async with Client(mcp) as c:
        hedef = str(tmp_path / "h.html")
        r = await c.call_tool("zihin_haritasi", {"metin": "", "html_dosya": hedef})
        assert r.data["durum"] == "icerik_yok"
        import pathlib

        assert not pathlib.Path(hedef).exists()


async def test_seslendir_hata_durumunda_dosya_yok(tmp_output_base, tmp_path):
    async with Client(mcp) as c:
        r = await c.call_tool("seslendir", {"metin": ""})
        assert r.data["durum"] == "icerik_yok" and r.data["dosya"] is None


async def test_kurulum_kontrol_ner_fixture_gozlemlenebilir(tmp_output_base, monkeypatch):
    # review tur-1 MED: YT_NER_FIXTURE fail-open seam'i operatore GORUNUR olmali.
    async with Client(mcp) as c:
        r = await c.call_tool("kurulum_kontrol", {})
        assert r.data["ner_fixture_aktif"] is True  # conftest set ediyor — gorunur


# --- denetim: MCP tool yuzeyinin KVKK gate'leri mutasyon-kontrollu (onceden testsizdi) ---


def test_ses_modeli_indir_zaten_varsa_indirmez(tmp_output_base, monkeypatch):
    # Model hazırsa ağa GİTMEZ (gereksiz 60MB indirme yok); 'zaten_var' döner.
    from ytcore.uretim import tts
    from ytmcp import tools

    monkeypatch.setattr(tts, "piper_hazir_mi", lambda _d: True)

    def _patlasin(_d=None):
        raise AssertionError("model hazırken piper_voice_indir çağrılmamalı")

    monkeypatch.setattr(tts, "piper_voice_indir", _patlasin)
    r = tools.ses_modeli_indir_core()
    assert r["durum"] == "zaten_var"


def test_ses_modeli_indir_basarili(tmp_output_base, monkeypatch):
    # piper_voice_indir başarılı + sonrasında hazır → 'indirildi' (ağ yok: indir monkeypatch'li).
    from ytcore.uretim import tts
    from ytmcp import tools

    durum = {"hazir": False}
    monkeypatch.setattr(tts, "piper_hazir_mi", lambda _d: durum["hazir"])

    def _indir(_d=None):
        durum["hazir"] = True  # indirme sonrası model hazır

    monkeypatch.setattr(tts, "piper_voice_indir", _indir)
    r = tools.ses_modeli_indir_core()
    assert r["durum"] == "indirildi"


def test_ses_modeli_indir_eksik_dosya_hata(tmp_output_base, monkeypatch):
    # 'boş≠başarı': piper_voice_indir EXCEPTION FIRLATMAZ ama dosyalar eksik kalırsa (kesik/kısmi
    # indirme, HF 200-ama-eksik) 'indirildi' DEĞİL 'hata' döner (yarım indirme başarı sayılmaz).
    from ytcore.uretim import tts
    from ytmcp import tools

    monkeypatch.setattr(tts, "piper_hazir_mi", lambda _d: False)  # indirme sonrası hâlâ hazır değil
    monkeypatch.setattr(tts, "piper_voice_indir", lambda _d=None: None)  # no-op, exception YOK
    r = tools.ses_modeli_indir_core()
    assert r["durum"] == "hata" and "eksik dosya" in r["hata"]


def test_ses_modeli_indir_ag_hatasi_graceful(tmp_output_base, monkeypatch):
    # Ağ hatası ÇÖKERTMEZ (graceful) — 'hata' durumu + mesaj döner (boş≠başarı).
    import httpx
    from ytcore.uretim import tts
    from ytmcp import tools

    monkeypatch.setattr(tts, "piper_hazir_mi", lambda _d: False)

    def _kopuk(_d=None):
        raise httpx.ConnectError("baglanti yok")

    monkeypatch.setattr(tts, "piper_voice_indir", _kopuk)
    r = tools.ses_modeli_indir_core()
    assert r["durum"] == "hata" and "ConnectError" in r["hata"]


def test_seslendir_core_pii_cloud_acikken_yerele_duser(tmp_output_base, monkeypatch):
    # MCP seslendir_core KVKK gate'i (tts_pii_var_mi): PII'li metin + cloud AÇIK + anahtar VAR
    # → karar yine de YEREL (fail-closed). Gate bypass edilse gerekce 'cloud opt-in' olurdu.
    from ytmcp import tools

    monkeypatch.setenv("YT_TTS_CLOUD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    r = tools.seslendir_core("Müvekkilin T.C. kimlik numarası 12345678901 olarak kayıtlı.")
    assert "pii" in r["gerekce"].lower()  # KVKK fail-closed → yerel
    assert r["kaynak"] != "cloud"  # PII içerik cloud TTS'e GİTMEDİ


def test_fact_check_core_web_mumkunse_ner_baglanir(tmp_output_base, monkeypatch):
    # fact_check_core web-egress mümkünken (YT_WEBSEARCH_FIXTURE — conftest) NER'i fact_check'e
    # BAĞLAMALI (çıplak ad-soyad egress guard'ı). Wiring silinse ner=None geçerdi → KIRMIZI.
    import ytcore.intel.factcheck as fc
    from ytmcp import tools

    yakalanan: dict[str, object] = {}

    def _capture(metin, llm, web, *, model, ner=None, cloud=None, web_mumkun=False):
        yakalanan["ner"] = ner
        return ([], "uretildi")

    monkeypatch.setattr(fc, "fact_check", _capture)
    tools.fact_check_core("Bir olgusal iddia metni.")
    assert yakalanan["ner"] is not None  # web mümkün → NER bağlandı (egress guard aktif)


# --- Faz 8: NER durum probe + kurulum_kontrol yüzeyi (GUI rozeti — tam web fact-check) ---


def test_ner_erisilebilir_fixture_aktifken_spawnsiz_true(monkeypatch):
    # Hermetik/selftest: YT_NER_FIXTURE set → FakeNER her zaman hazır; subprocess SPAWN edilmez.
    from ytmcp.tools import _ner_erisilebilir_mi

    monkeypatch.setenv("YT_NER_FIXTURE", "1")

    def patlat(*a, **k):
        raise AssertionError("fixture aktifken spawn olmamalı")

    monkeypatch.setattr(subprocess, "run", patlat)
    assert _ner_erisilebilir_mi() is True


def test_ner_erisilebilir_transformers_varsa_true(monkeypatch):
    # ner_python transformers'ı import edebiliyorsa (probe returncode 0) → erişilebilir.
    from ytmcp.tools import _ner_erisilebilir_mi

    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0))
    assert _ner_erisilebilir_mi() is True


def test_ner_erisilebilir_transformers_yoksa_false(monkeypatch):
    # probe returncode 1 (transformers yok — ör. budanmış .venv) → erişilemez.
    from ytmcp.tools import _ner_erisilebilir_mi

    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=1))
    assert _ner_erisilebilir_mi() is False


def test_ner_erisilebilir_spawn_hatasi_false(monkeypatch):
    # python yolu bozuk/timeout → erişilemez (best-effort durum; kritik yol değil).
    from ytmcp.tools import _ner_erisilebilir_mi

    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)

    def patlat(*a, **k):
        raise OSError("python yok")

    monkeypatch.setattr(subprocess, "run", patlat)
    assert _ner_erisilebilir_mi() is False


def test_ner_erisilebilir_frozen_self_spawnsiz_false(monkeypatch):
    # Frozen exe + ner_python == sys.executable (transformers PYZ'de YOK) → spawn ETMEDEN False.
    from ytmcp.tools import _ner_erisilebilir_mi

    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    monkeypatch.setenv("YT_NER_PYTHON", sys.executable)  # config.ner_python = sys.executable
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def patlat(*a, **k):
        raise AssertionError("frozen-self spawn olmamalı")

    monkeypatch.setattr(subprocess, "run", patlat)
    assert _ner_erisilebilir_mi() is False


def test_ner_erisilebilir_probe_secret_pythonpath_sizdirmaz(monkeypatch):
    # GÜVENLİK (review HIGH): probe subprocess'i API anahtarlarını + PYTHONPATH'i çocuğa MİRAS
    # ETMEMELİ (poisoned-python senaryosu + worker-sandbox hijyeni; find_spec yalnız PATH ister).
    from ytmcp.tools import _ner_erisilebilir_mi

    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-gizli-123")
    monkeypatch.setenv("PYTHONPATH", "/saldirgan/yol")
    yakalanan: dict = {}

    def sahte_run(cmd, **k):
        yakalanan["env"] = k.get("env")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setenv("FOO_TOKEN", "t")  # gelecekteki secret (son-ek deseni yakalamalı)
    monkeypatch.setattr(subprocess, "run", sahte_run)
    assert _ner_erisilebilir_mi() is True
    env = yakalanan["env"]
    assert env is not None
    assert "ANTHROPIC_API_KEY" not in env  # _API_KEY son-eki
    assert "FOO_TOKEN" not in env  # _TOKEN son-eki (deny-list değil desen → gelecek-korumalı)
    assert "PYTHONPATH" not in env


def test_ner_erisilebilir_frozen_self_yol_varyanti_spawnsiz_false(monkeypatch):
    # GÜVENLİK (review tur-2): tools.py frozen-self guard'ı da NORMALİZE yol karşılaştırmalı
    # (ner.py _ayni_yol emsali). Aynı exe'ye işaret eden farklı string (../) → spawn YOK.
    from ytmcp.tools import _ner_erisilebilir_mi

    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    exe = Path(sys.executable)
    varyant = str(exe.parent / ".." / exe.parent.name / exe.name)
    monkeypatch.setenv("YT_NER_PYTHON", varyant)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def patlat(*a, **k):
        raise AssertionError("frozen-self (yol varyantı) spawn etmemeli!")

    monkeypatch.setattr(subprocess, "run", patlat)
    assert _ner_erisilebilir_mi() is False


def test_ner_kaynak_env_ve_dev(monkeypatch):
    # _ner_kaynak teşhis alanı: YT_NER_PYTHON set → 'env'; frozen değil + env yok → 'dev'.
    from ytmcp.tools import _ner_kaynak

    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("YT_NER_PYTHON", r"C:\x\python.exe")
    assert _ner_kaynak() == "env"
    monkeypatch.delenv("YT_NER_PYTHON")
    assert _ner_kaynak() == "dev"


async def test_kurulum_kontrol_ner_durum_alanlari(tmp_output_base):
    # GUI rozeti: kurulum_kontrol ner_erisilebilir + ner_kaynak döndürmeli. conftest
    # YT_NER_FIXTURE=1 → kaynak 'fixture', erişilebilir True (FakeNER selftest yolu).
    async with Client(mcp) as c:
        r = await c.call_tool("kurulum_kontrol", {})
        assert r.data["ner_erisilebilir"] is True
        assert r.data["ner_kaynak"] == "fixture"
