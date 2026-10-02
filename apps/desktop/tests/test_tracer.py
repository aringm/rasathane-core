from __future__ import annotations

from ytcore.obs.tracer import bellek_tracer_kur, span_baslat


def test_spanlar_yakalanir():
    exporter = bellek_tracer_kur()
    with span_baslat("deneme", {"hedef": "local"}):
        pass
    spans = exporter.get_finished_spans()
    assert any(s.name == "deneme" for s in spans)
