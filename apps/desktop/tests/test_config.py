from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from ytcore.config import _loopback_host_mi, _ner_python_bul, get_config


def test_config_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-xxx")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("YT_OUTPUT_BASE", str(tmp_path))
    c = get_config()
    assert c.anthropic_api_key == "sk-ant-api03-xxx"
    assert c.ollama_host == "http://127.0.0.1:11434"
    assert c.output_base == tmp_path


def test_config_no_key_is_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_config().anthropic_api_key is None


def test_yeni_env_alanlari(monkeypatch):
    monkeypatch.setenv("YT_POT_BASE_URL", "http://127.0.0.1:4416")
    monkeypatch.setenv("YT_COOKIES_BROWSER", "firefox")
    c = get_config()
    assert c.pot_base_url == "http://127.0.0.1:4416"
    assert c.cookies_browser == "firefox"


def test_yeni_env_varsayilan_none(monkeypatch):
    monkeypatch.delenv("YT_POT_BASE_URL", raising=False)
    monkeypatch.delenv("YT_COOKIES_BROWSER", raising=False)
    c = get_config()
    assert c.pot_base_url is None
    assert c.cookies_browser is None
    assert c.asr_python  # sys.executable fallback boş değil


def test_faz2_model_config_varsayilanlari(monkeypatch):
    for k in (
        "YT_EMBED_MODEL",
        "YT_CEVIRI_MODEL",
        "YT_MAP_MODEL",
        "YT_REDUCE_MODEL",
        "YT_JUDGE_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)
    c = get_config()
    assert c.ollama_embedding_model == "bge-m3"
    assert c.ollama_ceviri_model == "qwen2.5:14b"
    assert c.ollama_map_model == "qwen2.5:14b"
    assert c.ollama_reduce_model == "qwen2.5:14b"
    assert c.ollama_judge_model == "qwen2.5:14b"


def test_faz2_model_config_env_override(monkeypatch):
    monkeypatch.setenv("YT_MAP_MODEL", "gemma4:12b")
    assert get_config().ollama_map_model == "gemma4:12b"


def test_ping_default_kurulu_model(monkeypatch):
    # Faz 2: ping default qwen3:8b DEĞİL (makinede yok) → qwen2.5:14b
    monkeypatch.delenv("OLLAMA_PING_MODEL", raising=False)
    assert get_config().ollama_ping_model == "qwen2.5:14b"


def test_num_ctx_default_16gb_guard(monkeypatch):
    # ≤16GB (#2): num_ctx default 8192 (qwen2.5:14b@32K=17GB tek-GPU'ya sığmaz)
    monkeypatch.delenv("YT_OLLAMA_NUM_CTX", raising=False)
    assert get_config().ollama_num_ctx == 8192


def test_num_ctx_env_override(monkeypatch):
    monkeypatch.setenv("YT_OLLAMA_NUM_CTX", "4096")
    assert get_config().ollama_num_ctx == 4096


@pytest.mark.parametrize(
    "host,beklenen",
    [
        ("http://127.0.0.1:11434", True),
        ("http://localhost:11434", True),
        ("http://[::1]:11434", True),
        ("http://127.0.0.5:11434", True),
        ("http://192.168.1.10:11434", False),
        ("https://uzak-sunucu.com:11434", False),
        ("http://10.0.0.1:11434", False),
    ],
)
def test_loopback_host_mi(host, beklenen):
    assert _loopback_host_mi(host) is beklenen


def test_uzak_ollama_host_reddedilir(monkeypatch):
    # KVKK fail-closed (#1): uzak OLLAMA_HOST opt-in olmadan REDDEDILIR
    monkeypatch.setenv("OLLAMA_HOST", "https://uzak-sunucu.com:11434")
    monkeypatch.delenv("YT_ALLOW_REMOTE_OLLAMA", raising=False)
    with pytest.raises(ValueError, match="KVKK fail-closed"):
        get_config()


def test_uzak_ollama_host_opt_in_ile_kabul(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://uzak-sunucu.com:11434")
    monkeypatch.setenv("YT_ALLOW_REMOTE_OLLAMA", "1")
    c = get_config()
    assert c.ollama_host == "https://uzak-sunucu.com:11434"


def test_loopback_ollama_host_default_kabul(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("YT_ALLOW_REMOTE_OLLAMA", raising=False)
    assert _loopback_host_mi(get_config().ollama_host)


def test_config_faz3_alanlari(monkeypatch):
    # Faz 3: serper/tavily key (env, hardcode YASAK → None), model'ler, index/kullanıcı base.
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    c = get_config()
    assert c.serper_api_key is None
    assert c.tavily_api_key is None
    assert c.ollama_verdict_model == "qwen2.5:14b"
    assert c.ollama_claim_model == "qwen2.5:14b"
    assert c.ollama_memory_model == "qwen2.5:14b"
    assert c.ollama_eval_embedding_model == "qwen3-embedding:8b"
    assert c.index_base.name == "_index"
    assert c.kullanici_base.name == "_kullanici"
    # Ağırlıklar toplamı 1 (BilgiDeğeri 0-100 normalize)
    assert abs(sum(c.degerleme_agirliklari.values()) - 1.0) < 1e-9


def test_config_faz3_key_env(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "sk-serper-xxx")
    assert get_config().serper_api_key == "sk-serper-xxx"


def test_config_faz3_base_output_altinda(monkeypatch, tmp_path):
    monkeypatch.setenv("YT_OUTPUT_BASE", str(tmp_path))
    c = get_config()
    assert c.index_base == tmp_path / "_index"
    assert c.kullanici_base == tmp_path / "_kullanici"


def test_config_faz4_alanlari(monkeypatch):
    # Faz 4: cloud TTS anahtarı env (hardcode YASAK → None), cloud default kapalı (opt-in),
    # Piper voice output altında, harita LLM qwen2.5:14b reuse.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("YT_TTS_CLOUD", raising=False)
    monkeypatch.delenv("YT_PIPER_VOICE_DIR", raising=False)
    monkeypatch.delenv("YT_HARITA_MODEL", raising=False)
    c = get_config()
    assert c.openai_api_key is None
    assert c.tts_cloud_model == "gpt-4o-mini-tts"
    assert c.tts_cloud_acik is False
    assert c.piper_voice_dir.name == "piper"
    assert c.harita_model == "qwen2.5:14b"


def test_config_faz4_cloud_opt_in_ve_anahtar(monkeypatch):
    monkeypatch.setenv("YT_TTS_CLOUD", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-xxx")
    c = get_config()
    assert c.tts_cloud_acik is True
    assert c.openai_api_key == "sk-openai-xxx"


def test_config_faz4_piper_voice_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("YT_PIPER_VOICE_DIR", str(tmp_path / "sesler"))
    assert get_config().piper_voice_dir == tmp_path / "sesler"


def test_faz5_config_alanlari(monkeypatch):
    # Faz 5: NER ayrı-proses python'u (ASR deseni), cloud verdict modeli (A11: Sonnet),
    # cloud verdict bilinçli opt-in (KVKK — TTS YT_TTS_CLOUD emsali, default KAPALI).
    monkeypatch.delenv("YT_NER_PYTHON", raising=False)
    monkeypatch.delenv("YT_ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("YT_CLOUD_VERDICT", raising=False)
    cfg = get_config()
    assert cfg.ner_python  # default: sys.executable
    assert cfg.anthropic_model == "claude-sonnet-4-6"
    assert cfg.cloud_verdict_acik is False


def test_faz5_config_env_override(monkeypatch):
    monkeypatch.setenv("YT_NER_PYTHON", r"C:\ner-env\python.exe")
    monkeypatch.setenv("YT_ANTHROPIC_MODEL", "claude-opus-4-8")
    monkeypatch.setenv("YT_CLOUD_VERDICT", "1")
    cfg = get_config()
    assert cfg.ner_python == r"C:\ner-env\python.exe"
    assert cfg.anthropic_model == "claude-opus-4-8"
    assert cfg.cloud_verdict_acik is True


# --- Faz 8: NER python oto-tespit (ayrı NER env — ASR/Piper emsali; frozen exe'de torch-dışı) ---


def test_ner_python_bul_env_override_her_seyi_ezer(monkeypatch):
    # Açık YT_NER_PYTHON en yüksek öncelik (frozen olsa bile) — runbook/farklı kurulum.
    monkeypatch.setenv("YT_NER_PYTHON", r"C:\ozel\python.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _ner_python_bul() == r"C:\ozel\python.exe"


def test_ner_python_bul_dev_sys_executable(monkeypatch):
    # Frozen DEĞİL + env yok → sys.executable (dev'de zaten .venv python; ner grubu sync'liyse
    # transformers var). Oto-tespit yalnız frozen exe'de devreye girer (dev'de gereksiz).
    monkeypatch.delenv("YT_NER_PYTHON", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert _ner_python_bul() == sys.executable


def test_ner_python_bul_frozen_venv_oto_tespit(monkeypatch, tmp_path):
    # Frozen exe (sys.executable = exe; transformers PYZ'de YOK) + env yok: repo .venv python'unu
    # exe konumundan YUKARI YÜRÜYEREK bul (ağır-runtime exe-DIŞI; ASR/Piper emsali).
    proj = tmp_path / "proj"
    rel = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    venv_py = proj / ".venv" / rel
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("")  # VARLIK yeterli (ucuz); transformers probe ayrı (kurulum_kontrol)
    exe = proj / "gui" / "src-tauri" / "binaries" / "sidecar.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.delenv("YT_NER_PYTHON", raising=False)
    monkeypatch.setattr("ytcore.config.motor_kok_bul", lambda: None)  # motor_kok yok
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert _ner_python_bul() == str(venv_py.resolve())


def test_ner_python_bul_frozen_venv_yok_fail_closed(monkeypatch, tmp_path):
    # Frozen + env yok + .venv bulunamadı → sys.executable döner (SubprocessNER frozen-guard'ı
    # spawn ETMEDEN fail-closed döner; sessiz fail-open YOK).
    izole = tmp_path / "izole"
    exe = izole / "sidecar.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.delenv("YT_NER_PYTHON", raising=False)
    monkeypatch.setattr("ytcore.config.motor_kok_bul", lambda: None)  # motor_kok yok
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert _ner_python_bul() == str(exe)


def test_ner_python_bul_frozen_guvenilmez_cwd_secilmez(monkeypatch, tmp_path):
    # GÜVENLİK (review HIGH path-traversal): frozen exe GÜVENİLMEYEN cwd'den başlatılırsa, cwd'ye
    # konmuş SAHTE .venv SPAWN EDİLMEMELİ (keyfi-python = KVKK fail-OPEN). Walk-up YALNIZ
    # sys.executable (güvenilen exe konumu) kökünden; cwd kök DEĞİL.
    saldirgan = tmp_path / "indirilenler"  # güvenilmez cwd (ör. Downloads)
    rel = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    sahte = saldirgan / ".venv" / rel
    sahte.parent.mkdir(parents=True)
    sahte.write_text("")  # saldırganın planladığı sahte python
    exe = tmp_path / "izole" / "sidecar.exe"  # sys.executable repo DIŞINDA, .venv yok
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.delenv("YT_NER_PYTHON", raising=False)
    monkeypatch.setattr("ytcore.config.motor_kok_bul", lambda: None)  # motor_kok yok
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.chdir(saldirgan)  # güvenilmez cwd = saldırgan dizini
    assert _ner_python_bul() == str(exe)  # sahte cwd .venv SEÇİLMEZ → fail-closed


def test_motor_kok_env_oncelik_ner_tts_python(monkeypatch, tmp_path):
    # Faz 10: YT_MOTOR_KOK geçerli (.venv + core/ytcore) → motor_kok_bul onu döndürür ve
    # NER/TTS worker python'u o motorun .venv'inden gelir (kurulu app'i tam özellik yapan yol).
    from ytcore.config import _tts_python_bul, motor_kok_bul

    rel = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    kok = tmp_path / "motor"
    venv_py = kok / ".venv" / rel
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("")
    (kok / "core" / "ytcore").mkdir(parents=True)
    monkeypatch.delenv("YT_NER_PYTHON", raising=False)
    monkeypatch.delenv("YT_TTS_PYTHON", raising=False)
    monkeypatch.setenv("YT_MOTOR_KOK", str(kok))
    assert motor_kok_bul() == kok.resolve()
    assert _ner_python_bul() == str(venv_py.resolve())
    assert _tts_python_bul() == str(venv_py.resolve())


def test_motor_kok_gecersiz_env_secilmez(monkeypatch, tmp_path):
    # Geçersiz YT_MOTOR_KOK (.venv/core yok) SEÇİLMEZ — keyfi klasör worker kökü olamaz.
    from ytcore.config import motor_kok_bul

    bos = tmp_path / "bos"
    bos.mkdir()
    monkeypatch.setenv("YT_MOTOR_KOK", str(bos))
    assert motor_kok_bul() != bos.resolve()
