"""Phase 32-v: Voice override storage testleri.

`load_voice_overrides`, `save_voice_overrides`, `get_active_voice_mapping`
helpers — JSON dosyası IO + merge mantığı.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from llm.tts import (
    PODCAST_VOICES_ELEVENLABS_BRIEF,
    get_active_voice_mapping,
    load_voice_overrides,
    save_voice_overrides,
)


@pytest.fixture
def temp_overrides_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override path'i izole tmp dizine yönlendir (gerçek data/ kirletme).

    Phase 35-viii: agent_profiles bridge eklendi — `get_active_voice_mapping`
    artık agent_profiles.json'dan da voice_id okuyor. Test izolasyonu için
    agent_profiles env'ini de tmp'ye yönlendirip "yok" senaryosu yaratıyoruz.
    Test'in kendi agent_profiles fixture'ını override etmesi mümkün.
    """
    p = tmp_path / "voice_overrides.json"
    monkeypatch.setenv("RASATHANE_VOICE_OVERRIDES_PATH", str(p))
    monkeypatch.setenv("RASATHANE_AGENT_PROFILES_PATH", str(tmp_path / "_agent_profiles.json"))
    return p


# ── load_voice_overrides ────────────────────────────────────────────────


def test_load_missing_file_returns_empty_dict(temp_overrides_path: Path) -> None:
    """Dosya yoksa boş dict döner — fresh install case."""
    assert not temp_overrides_path.exists()
    assert load_voice_overrides() == {}


def test_load_valid_json_returns_data(temp_overrides_path: Path) -> None:
    """Geçerli JSON dosyası → parse + return."""
    data = {"elevenlabs": {"brief": {"Filiz": "test_voice_id"}}}
    temp_overrides_path.write_text(json.dumps(data), encoding="utf-8")
    assert load_voice_overrides() == data


def test_load_corrupt_json_returns_empty_dict_with_warning(
    temp_overrides_path: Path,
) -> None:
    """Bozuk JSON → boş dict + log warning. Pipeline patlamaz."""
    temp_overrides_path.write_text("not valid json {{{", encoding="utf-8")
    assert load_voice_overrides() == {}


def test_load_non_dict_root_returns_empty(temp_overrides_path: Path) -> None:
    """Root array veya string ise → boş dict (schema sanity)."""
    temp_overrides_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_voice_overrides() == {}


# ── save_voice_overrides ────────────────────────────────────────────────


def test_save_writes_atomic_json(temp_overrides_path: Path) -> None:
    """save → dosya yazılmış + read ile geri alınabilir."""
    data = {"elevenlabs": {"brief": {"Filiz": "abc", "Mehmet": "def"}}}
    assert save_voice_overrides(data) is True
    assert temp_overrides_path.is_file()
    loaded = json.loads(temp_overrides_path.read_text(encoding="utf-8"))
    assert loaded == data


def test_save_creates_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent dir yoksa otomatik oluştur."""
    nested = tmp_path / "deep" / "nested" / "voice_overrides.json"
    monkeypatch.setenv("RASATHANE_VOICE_OVERRIDES_PATH", str(nested))
    assert save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "x"}}}) is True
    assert nested.is_file()


def test_save_overwrites_existing(temp_overrides_path: Path) -> None:
    """İkinci save tüm config'i replace eder (partial merge sorumluluğu client'ta)."""
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "first"}}})
    save_voice_overrides({"elevenlabs": {"brief": {"Mehmet": "second"}}})
    loaded = load_voice_overrides()
    assert loaded == {"elevenlabs": {"brief": {"Mehmet": "second"}}}
    # Filiz silindi — replace semantiği


def test_save_atomic_tmp_pattern_cleaned_up(temp_overrides_path: Path) -> None:
    """.tmp dosyası işlem sonu silinir (atomic rename pattern)."""
    save_voice_overrides({"elevenlabs": {}})
    tmp_path = temp_overrides_path.with_suffix(temp_overrides_path.suffix + ".tmp")
    assert not tmp_path.exists()


# ── get_active_voice_mapping ────────────────────────────────────────────


def test_get_active_no_overrides_returns_defaults(temp_overrides_path: Path) -> None:
    """Override dosyası yoksa default mapping aynısı dönmeli."""
    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )
    assert result == PODCAST_VOICES_ELEVENLABS_BRIEF


def test_get_active_applies_speaker_override(temp_overrides_path: Path) -> None:
    """Override voice_id'yi değiştirir; diğer alanlar default'tan korunur."""
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "MY_CUSTOM_VOICE_123"}}})
    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )
    assert result["Filiz"]["voice_id"] == "MY_CUSTOM_VOICE_123"
    # Stability/similarity_boost/style default'tan korunur
    assert result["Filiz"]["stability"] == PODCAST_VOICES_ELEVENLABS_BRIEF["Filiz"]["stability"]
    assert (
        result["Filiz"]["similarity_boost"]
        == PODCAST_VOICES_ELEVENLABS_BRIEF["Filiz"]["similarity_boost"]
    )
    # Diğer speaker'lar etkilenmez
    assert result["Mehmet"]["voice_id"] == PODCAST_VOICES_ELEVENLABS_BRIEF["Mehmet"]["voice_id"]
    assert result["Burak"]["voice_id"] == PODCAST_VOICES_ELEVENLABS_BRIEF["Burak"]["voice_id"]


def test_get_active_partial_override_only_changes_specified(temp_overrides_path: Path) -> None:
    """3 speaker'dan sadece 1'i override → 1 değişir, 2'si default kalır."""
    save_voice_overrides({"elevenlabs": {"brief": {"Mehmet": "OVERRIDDEN_MEHMET"}}})
    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )
    assert result["Filiz"]["voice_id"] == PODCAST_VOICES_ELEVENLABS_BRIEF["Filiz"]["voice_id"]
    assert result["Mehmet"]["voice_id"] == "OVERRIDDEN_MEHMET"
    assert result["Burak"]["voice_id"] == PODCAST_VOICES_ELEVENLABS_BRIEF["Burak"]["voice_id"]


def test_get_active_different_role_returns_defaults(temp_overrides_path: Path) -> None:
    """brief override'ı youtube'u etkilemez."""
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "BRIEF_ONLY"}}})
    # YouTube mapping istendi — brief override'ı dokunmamalı
    youtube_default = {
        "Filiz": {"voice_id": "YT_DEFAULT", "stability": 0.5},
        "Burak": {"voice_id": "YT_BURAK", "stability": 0.5},
    }
    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="youtube",
        default_mapping=youtube_default,
    )
    assert result["Filiz"]["voice_id"] == "YT_DEFAULT"


def test_get_active_unknown_provider_returns_defaults(temp_overrides_path: Path) -> None:
    """Override config'te bilinmeyen provider istendi → defaults döner."""
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "X"}}})
    # Bilinmeyen 'legacy_provider' istedik ama override 'elevenlabs' altında
    result = get_active_voice_mapping(
        provider="legacy_provider",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )
    assert result == PODCAST_VOICES_ELEVENLABS_BRIEF


def test_get_active_unknown_speaker_in_override_ignored(temp_overrides_path: Path) -> None:
    """Override'da default'ta olmayan speaker varsa atla."""
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "OK_FILIZ", "BilinmeyenSpiker": "X"}}})
    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )
    assert result["Filiz"]["voice_id"] == "OK_FILIZ"
    assert "BilinmeyenSpiker" not in result


def test_get_active_empty_string_override_keeps_default(temp_overrides_path: Path) -> None:
    """voice_id boş string ise default korunur (override silme sinyali)."""
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": ""}}})
    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )
    assert result["Filiz"]["voice_id"] == PODCAST_VOICES_ELEVENLABS_BRIEF["Filiz"]["voice_id"]


# ── Phase 35-viii: Stüdyo UI (agent_profiles.json) bridge ───────────────


@pytest.fixture
def temp_agent_profiles_path(
    temp_overrides_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Agent profiles path'i tmp dizine yönlendir.

    `temp_overrides_path`'a depend → pytest sıralı çalıştırır: önce overrides
    fixture env'i set eder (default `_agent_profiles.json` boş path), sonra
    bu fixture aynı env var'ı dolu path'e override eder. Determinist sıra.
    """
    p = tmp_path / "agent_profiles.json"
    monkeypatch.setenv("RASATHANE_AGENT_PROFILES_PATH", str(p))
    return p


def test_get_active_reads_voice_ids_from_agent_profiles(
    temp_overrides_path: Path, temp_agent_profiles_path: Path
) -> None:
    """Phase 35-viii: Stüdyo UI agent_profiles.json'a yazdığı voice_id brief mapping'e yansır.

    Önceki davranış: brief audio sadece voice_overrides.json okuyordu; Stüdyo UI
    Phase 35-ii'den itibaren agent_profiles.json'a yazıyor → kopukluk vardı,
    kullanıcı seçimi default'a düşüyordu. Bu test bağlantıyı pin'ler.
    """
    # Stüdyo UI'nın yazacağı şema (line 1038 agents pool + line 1056 modes)
    studio_save = {
        "agents": {
            "filiz": {"name": "Filiz", "voice_id": "STUDIO_FILIZ_ID"},
            "mehmet": {"name": "Mehmet", "voice_id": "STUDIO_MEHMET_ID"},
            "burak": {"name": "Burak", "voice_id": "STUDIO_BURAK_ID"},
        },
        "modes": {
            "brief": [
                {"agent_id": "filiz", "role": "Spiker"},
                {"agent_id": "mehmet", "role": "Hukuk"},
                {"agent_id": "burak", "role": "AI"},
            ],
        },
    }
    temp_agent_profiles_path.write_text(json.dumps(studio_save), encoding="utf-8")

    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )

    assert result["Filiz"]["voice_id"] == "STUDIO_FILIZ_ID"
    assert result["Mehmet"]["voice_id"] == "STUDIO_MEHMET_ID"
    assert result["Burak"]["voice_id"] == "STUDIO_BURAK_ID"
    # Voice settings default'tan (Phase 35-vii anchor tuning) korunur
    assert result["Filiz"]["style"] == 0.40
    assert result["Mehmet"]["style"] == 0.30


def test_agent_profiles_primary_legacy_voice_overrides_fallback(
    temp_overrides_path: Path, temp_agent_profiles_path: Path
) -> None:
    """Hem agent_profiles hem voice_overrides varsa → agent_profiles kazanır."""
    temp_agent_profiles_path.write_text(
        json.dumps(
            {
                "agents": {"filiz": {"name": "Filiz", "voice_id": "STUDIO_WINS"}},
                "modes": {"brief": [{"agent_id": "filiz", "role": "Spiker"}]},
            }
        ),
        encoding="utf-8",
    )
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "LEGACY_LOSES"}}})

    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )

    assert result["Filiz"]["voice_id"] == "STUDIO_WINS"


def test_no_agent_profiles_falls_back_to_legacy_voice_overrides(
    temp_overrides_path: Path, temp_agent_profiles_path: Path
) -> None:
    """agent_profiles boş + voice_overrides dolu → legacy override kullanılır."""
    # agent_profiles.json yok (fixture path'i set ama dosya yazılmadı)
    assert not temp_agent_profiles_path.exists()
    save_voice_overrides({"elevenlabs": {"brief": {"Filiz": "LEGACY_USED"}}})

    result = get_active_voice_mapping(
        provider="elevenlabs",
        role="brief",
        default_mapping=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )

    assert result["Filiz"]["voice_id"] == "LEGACY_USED"


def test_load_agent_profiles_handles_utf8_bom(
    temp_overrides_path: Path, temp_agent_profiles_path: Path
) -> None:
    """Phase 35-xi: UTF-8 BOM'lu JSON dosyası sessizce default'a düşmesin.

    Windows PowerShell `Set-Content -Encoding utf8` BOM ekliyor (WinPS 5.1
    default). BOM'lu dosya `utf-8` parse'ında JSONDecodeError verir,
    `load_agent_profiles` boş dict döner, endpoint default'a fallback eder.
    Symptom: kullanıcı Stüdyo'da voice seçti, kaydetti — UI "eski sesler
    seçili" gösteriyordu çünkü API current dict'i değil default'u dönüyordu.

    Fix: `utf-8-sig` codec (BOM varsa atlar, yoksa düz utf-8).
    """
    from llm.tts import load_agent_profiles

    payload = {
        "agents": {"filiz": {"name": "Filiz", "voice_id": "BOM_TEST_VOICE"}},
        "modes": {"brief": [{"agent_id": "filiz", "role": "Spiker"}]},
    }
    # UTF-8 BOM (﻿ = 0xEF 0xBB 0xBF) + payload
    temp_agent_profiles_path.write_bytes(
        "﻿".encode() + json.dumps(payload).encode("utf-8")
    )
    # Verify file really has BOM
    first_bytes = temp_agent_profiles_path.read_bytes()[:3]
    assert first_bytes == b"\xef\xbb\xbf", "test setup: BOM yazılmadı"

    result = load_agent_profiles()
    assert result, "BOM tolere edilmedi — fonksiyon boş dict döndü"
    assert result["agents"]["filiz"]["voice_id"] == "BOM_TEST_VOICE"
