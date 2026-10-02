from __future__ import annotations

import asyncio

from fastmcp import Client
from ytcore.obs.tracer import bellek_tracer_kur
from ytcore.pipeline.api import analiz_et
from ytmcp.server import analiz_et_core, mcp


def test_gui_ve_mcp_ayni_sonuc(tmp_output_base, tmp_path, monkeypatch):
    """DoD #10: GUI yolu ve MCP tool'u aynı çekirdeği çağırır -> aynı sonuç."""
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("YT_FORCE_COMPLEX", "0")
    gui = analiz_et_core("https://youtu.be/abc", "genel", "g")

    async def mcp_call():
        async with Client(mcp) as c:
            r = await c.call_tool(
                "analiz_et", {"url": "https://youtu.be/abc", "konu": "genel", "thread_id": "m"}
            )
            return r.data

    m = asyncio.run(mcp_call())
    assert gui["index"]["video_slug"] == m["index"]["video_slug"]
    assert gui["cloud_cagrisi_sayisi"] == m["cloud_cagrisi_sayisi"] == 0


def test_pii_0_cloud_trace(tmp_output_base, tmp_path, monkeypatch):
    """Değişmez #1 kanıtı (Faz 1): GERÇEK transkript metninde PII + COMPLEX olsa bile
    cloud çağrısı 0; cloud span YOK. PII artık fixture-pii altyazısının metninden gelir."""
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "pii")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "1")
    exporter = bellek_tracer_kur()
    s = analiz_et("https://youtu.be/pii", thread_id="pii", checkpoint_dir=tmp_path)
    assert s.pii_tespit is True
    assert s.cloud_cagrisi_sayisi == 0
    spans = {sp.name for sp in exporter.get_finished_spans()}
    # Transkript node trace edilir + gate gerçek metne uygulanır; cloud span YOK.
    assert "transcript" in spans and "pii_gate" in spans and "router" in spans
    assert not any("cloud" in n for n in spans)
