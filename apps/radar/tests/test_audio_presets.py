"""Phase 36-ii: AudioPreset şema + default 4 preset + storage."""

import json

from llm.presets import (
    DEFAULT_PRESETS,
    AudioPreset,
    load_user_presets,
    resolve_preset,
    save_user_presets,
)


def test_default_presets_count_and_ids():
    """4 default preset, sabit ID'ler."""
    ids = {p.id for p in DEFAULT_PRESETS}
    assert ids == {
        "klasik_panel",
        "hizli_brifing",
        "derin_uzman",
        "elestirel_munazara",
    }
    assert all(p.is_default for p in DEFAULT_PRESETS)


def test_resolve_preset_unknown_falls_back_to_klasik():
    """Bilinmeyen preset_id → klasik_panel fallback."""
    p = resolve_preset("bilinmeyen_xyz")
    assert p.id == "klasik_panel"


def test_resolve_preset_known_returns_match():
    p = resolve_preset("hizli_brifing")
    assert p.id == "hizli_brifing"
    assert p.format == "solo_narrator"
    assert p.target_minutes == (1.0, 2.0)


def test_load_user_presets_handles_missing_file(tmp_path):
    """Dosya yoksa boş list döner (sorunsuz)."""
    result = load_user_presets(tmp_path / "nope.json")
    assert result == []


def test_load_user_presets_handles_utf8_bom(tmp_path):
    """Phase 35-xi BOM defensive pattern preset storage'da da uygulanır."""
    path = tmp_path / "audio_presets.json"
    raw = json.dumps([{
        "id": "test_custom",
        "name": "Test",
        "description": "x",
        "format": "panel_3",
        "prompt_variant": "youtube_podcast_script",
        "target_minutes": [4.0, 7.0],
        "voices": {},
        "voice_settings": {},
        "is_default": False,
    }])
    path.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
    result = load_user_presets(path)
    assert len(result) == 1
    assert result[0].id == "test_custom"


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "audio_presets.json"
    p = AudioPreset(
        id="benim_preset",
        name="Benim",
        description="özel",
        format="duo_expert_critic",
        prompt_variant="youtube_podcast_script_deep",
        target_minutes=(6.0, 12.0),
        voices={"Burak": "kDaVLqYrOl8ui891kCrV"},
        voice_settings={"Burak": {"style": 0.55}},
        is_default=False,
    )
    save_user_presets([p], path)
    loaded = load_user_presets(path)
    assert len(loaded) == 1
    assert loaded[0].voices == {"Burak": "kDaVLqYrOl8ui891kCrV"}
    assert loaded[0].voice_settings == {"Burak": {"style": 0.55}}


def test_hizli_brifing_voices_filiz_irem_pin():
    """Phase 36-ii: hızlı brifing default Filiz voice TR-native İrem'e pin'li.
    Kullanıcının agent_profiles.json'daki Filiz override'ını (anglofon Matilda vb.)
    hızlı brifing preset'i ezer — TR-native akış garantili."""
    fast = next(p for p in DEFAULT_PRESETS if p.id == "hizli_brifing")
    assert fast.voices == {"Filiz": "hy7OAv1nH3Eqqj96Aude"}
