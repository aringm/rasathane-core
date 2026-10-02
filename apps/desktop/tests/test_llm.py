from __future__ import annotations

import pytest
from ytcore.content.llm import FakeLLM, llm_al


def test_fakellm_ceviri_gorevi():
    llm = FakeLLM()
    out = llm.uret("Aşağıdaki metni Türkçeye çevir.", "Hello world")
    assert out.strip()
    assert out != "Hello world"  # bir dönüşüm işaretledi


def test_fakellm_ozet_gorevi():
    llm = FakeLLM()
    out = llm.uret("Bu metni özetle.", "uzun cümle bir. uzun cümle iki. " * 50)
    assert out.strip()
    assert len(out) < len("uzun cümle bir. uzun cümle iki. " * 50)


def test_fakellm_judge_evet():
    llm = FakeLLM()
    out = llm.uret(
        "Bu iddia kaynak metinde destekleniyor mu? Yalnız EVET/HAYIR.", "iddia: x | kaynak: x"
    )
    assert out.strip().upper().startswith("EVET")


def test_fakellm_baslik():
    llm = FakeLLM()
    out = llm.uret("Bu bölüme kısa başlık üret.", "sözleşme hukuku temel ilkeler giriş")
    assert out.strip()


def test_llm_al_fixture_seam(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_LLM_FIXTURE", "1")
    assert isinstance(llm_al(), FakeLLM)


def test_llm_al_gercek_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("YT_LLM_FIXTURE", raising=False)
    # Gömülü motor (infra/vendor/motor) bu repoda VARSA auto llamacpp'e düşer; Ollama
    # varsayılanını kilitleyen bu sözleşme açıkça ollama backend'i sabitler.
    monkeypatch.setenv("YT_MOTOR_BACKEND", "ollama")
    from ytcore.content.llm import OllamaLLM

    assert isinstance(llm_al(), OllamaLLM)


def test_llm_al_llamacpp_backend(monkeypatch: pytest.MonkeyPatch):
    """motor_backend=llamacpp ise llm_al gömülü motor istemcisine yönlendirir."""
    monkeypatch.delenv("YT_LLM_FIXTURE", raising=False)
    monkeypatch.setenv("YT_MOTOR_BACKEND", "llamacpp")
    from ytcore.local.llamacpp import LlamaCppLLM

    assert isinstance(llm_al(), LlamaCppLLM)


def test_ollama_num_ctx_wire(monkeypatch: pytest.MonkeyPatch):
    # ≤16GB (#2) tek enforcement noktası — num_ctx ollama.chat'e GERÇEKTEN geçiyor mu (regresyon)
    import ollama
    from ytcore.content.llm import OllamaLLM

    kaydedilen: dict = {}

    class FakeClient:
        def __init__(self, host=None):
            pass

        def chat(self, **kw):
            kaydedilen.update(kw)
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(ollama, "Client", FakeClient)
    out = OllamaLLM(model="qwen2.5:14b").uret("sistem", "kullanici")
    assert out == "ok"
    assert kaydedilen["options"]["num_ctx"] == 8192  # config default cap


def test_ollama_num_ctx_override(monkeypatch: pytest.MonkeyPatch):
    import ollama
    from ytcore.content.llm import OllamaLLM

    kaydedilen: dict = {}

    class FakeClient:
        def __init__(self, host=None):
            pass

        def chat(self, **kw):
            kaydedilen.update(kw)
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(ollama, "Client", FakeClient)
    OllamaLLM(model="m", num_ctx=4096).uret("s", "k")
    assert kaydedilen["options"]["num_ctx"] == 4096
