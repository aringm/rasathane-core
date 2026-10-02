"""muhakeme.ai MCP client tests — env vars + payload parser.

The MCP transport layer (``_open_session``) requires the ``mcp`` package
plus an actual server to talk to. Phase 7 unit tests cover the configuration
gate and the payload-parsing logic; integration with a real server is
verified ad-hoc via ``pulse legal`` once the user provides MUHAKEME_MCP_URL.
"""

from __future__ import annotations

import pytest
from ingestion.muhakeme_mcp import (
    EmsalHit,
    MuhakemeNotConfiguredError,
    _parse_emsal_payload,
    search_emsals,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 7 tests pin env vars to known states for determinism."""
    monkeypatch.delenv("MUHAKEME_MCP_URL", raising=False)
    monkeypatch.delenv("MUHAKEME_MCP_COMMAND", raising=False)


async def test_search_emsals_raises_when_unconfigured() -> None:
    """No env vars → MuhakemeNotConfiguredError, surfaced as 503 by API."""
    with pytest.raises(MuhakemeNotConfiguredError):
        await search_emsals("test query")


async def test_search_emsals_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="empty query"):
        await search_emsals("")
    with pytest.raises(ValueError, match="empty query"):
        await search_emsals("   ")


def test_parse_emsal_payload_uses_turkish_field_names() -> None:
    """muhakeme tool may return Türkçe field names — parser handles both."""
    raw = {
        "mahkeme": "yargitay",
        "kararNo": "2024/123 E. 2024/456 K.",
        "baslik": "Nafaka artırımı kararı",
        "ozet": "Kısa özet metni.",
        "url": "https://example.com/karar/123",
    }
    hit = _parse_emsal_payload(raw)
    assert isinstance(hit, EmsalHit)
    assert hit.court == "yargitay"
    assert hit.case_id == "2024/123 E. 2024/456 K."
    assert hit.title == "Nafaka artırımı kararı"
    assert hit.excerpt == "Kısa özet metni."
    assert hit.url == "https://example.com/karar/123"
    assert hit.raw is raw


def test_parse_emsal_payload_falls_back_to_english_field_names() -> None:
    raw = {
        "court": "aym",
        "case_id": "Başvuru No: 2024/789",
        "title": "İfade özgürlüğü kararı",
        "excerpt": "Anayasa Mahkemesi kararı.",
    }
    hit = _parse_emsal_payload(raw)
    assert hit.court == "aym"
    assert hit.case_id == "Başvuru No: 2024/789"
    assert hit.url is None


def test_parse_emsal_payload_handles_missing_fields() -> None:
    """Best-effort: missing fields use sensible defaults."""
    hit = _parse_emsal_payload({})
    assert hit.court == "unknown"
    assert hit.case_id == ""
    assert hit.title == "(başlıksız)"


def test_parse_emsal_payload_uses_default_court_arg() -> None:
    hit = _parse_emsal_payload({"baslik": "x"}, default_court="danistay")
    assert hit.court == "danistay"


def test_emsal_hit_preserves_raw() -> None:
    """``raw`` field lets callers cite the original payload regardless of
    how field-name guessing went."""
    raw = {"random_field": "something", "ozet": "Test özet"}
    hit = _parse_emsal_payload(raw)
    assert hit.raw == raw


def test_muhakeme_not_configured_error_subclasses_runtime_error() -> None:
    """API endpoint catches RuntimeError-shaped failures uniformly."""
    err = MuhakemeNotConfiguredError("test")
    assert isinstance(err, RuntimeError)
