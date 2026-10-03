from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_provider: TracerProvider | None = None
_exporter: InMemorySpanExporter | None = None


def bellek_tracer_kur() -> InMemorySpanExporter:
    """Test: spanları bellekte yakala (cloud çağrısı kanıtı için).

    OTel global provider yalnız bir kez set edilebilir; exporter her çağrıda
    temizlenir (per-test izolasyon).
    """
    global _provider, _exporter
    if _provider is None:
        _exporter = InMemorySpanExporter()
        _provider = TracerProvider()
        _provider.add_span_processor(SimpleSpanProcessor(_exporter))
        trace.set_tracer_provider(_provider)
    assert _exporter is not None
    _exporter.clear()
    return _exporter


def phoenix_tracer_kur() -> None:
    """Prod: Arize Phoenix lokal trace (Docker yok, telemetri kapalı).

    KVKK (#1) veri-minimizasyonu: auto_instrument=False. auto_instrument LangChain/LangGraph
    enstrümantasyonunu açar, bu da node input/output value'larını (GState = PII transkript/
    çeviri/özet) span'lara serileştirir → PII ikinci bir yere (lokal trace store) yazılır.
    Manuel span_baslat yalnız güvenli durum/sayı attribute'ları kaydeder → bu yeterli.
    """
    from phoenix.otel import register

    register(project_name="rasathane", auto_instrument=False, batch=True)


@contextmanager
def span_baslat(ad: str, attrs: dict[str, str] | None = None) -> Iterator[None]:
    tracer = trace.get_tracer("rasathane")
    with tracer.start_as_current_span(ad) as span:
        for k, v in (attrs or {}).items():
            span.set_attribute(k, v)
        yield
