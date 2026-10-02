"""llama.cpp gömülü backend testleri — hermetik (ağsız: yalnız 127.0.0.1 stub sunucu).

Gerçek llama-server/GGUF gerektiren uçtan uca doğrulama paketli smoke'ta koşar; burada
istemci kontratı, profil/backend seçimi, KVKK guard ve sunucu-yaşam-döngüsü kararları
deterministik stub ile kilitlenir.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from ytcore.config import get_config
from ytcore.local import llamacpp


class _StubHandler(BaseHTTPRequestHandler):
    """llama-server OpenAI-uyumlu API taklidi (kayıt + deterministik yanıt)."""

    def log_message(self, *args: object) -> None:  # noqa: D102 - testte sessiz
        pass

    def do_GET(self) -> None:
        if self.path == "/health":
            self._gonder(200, {"status": "ok"})
        elif self.path == "/v1/models":
            self._gonder(200, {"data": [{"id": self.server.model_id}]})  # type: ignore[attr-defined]
        else:
            self._gonder(404, {})

    def do_POST(self) -> None:
        govde = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        istek = json.loads(govde or b"{}")
        self.server.kayitlar.append((self.path, istek))  # type: ignore[attr-defined]
        if self.path == "/v1/chat/completions":
            self._gonder(
                200,
                {"choices": [{"message": {"role": "assistant", "content": "stub yanit"}}]},
            )
        elif self.path == "/v1/embeddings":
            girisler = istek.get("input", [])
            # Sıra koruması 'index' üzerinden test edilsin diye kayıt ters döner.
            veri = [
                {"index": i, "embedding": [float(i), 1.0, 0.5]}
                for i in reversed(range(len(girisler)))
            ]
            self._gonder(200, {"data": veri})
        else:
            self._gonder(404, {})

    def _gonder(self, kod: int, veri: dict) -> None:
        govde = json.dumps(veri).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)


@pytest.fixture
def stub_sunucu():
    sunucu = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    sunucu.kayitlar = []  # type: ignore[attr-defined]
    sunucu.model_id = str(llamacpp.profil_bilgisi()["llm_dosya"])  # type: ignore[attr-defined]
    thread = threading.Thread(target=sunucu.serve_forever, daemon=True)
    thread.start()
    try:
        yield sunucu
    finally:
        sunucu.shutdown()
        thread.join(timeout=5)


def _stub_url(sunucu: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{sunucu.server_address[1]}"


# --- profil / backend seçimi -------------------------------------------------


def _motor_kur(monkeypatch: pytest.MonkeyPatch, tmp_path, profiller: list[str]):
    """Geçici motor köküne verilen profillerin model dosyalarını (boş) kur."""
    modeller = tmp_path / "modeller"
    modeller.mkdir(exist_ok=True)
    for p in profiller:
        for anahtar in ("llm_dosya", "embed_dosya"):
            (modeller / str(llamacpp.PROFILLER[p][anahtar])).write_bytes(b"gguf")
    monkeypatch.setenv("RASATHANE_MOTOR_DIR", str(tmp_path))


def test_aktif_profil_auto_ram8(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _motor_kur(monkeypatch, tmp_path, ["ram8", "ram16"])
    monkeypatch.delenv("YT_LLAMACPP_PROFIL", raising=False)
    monkeypatch.setattr("ytcore.config.fiziksel_ram_gb", lambda: 8.0)
    assert llamacpp.aktif_profil() == "ram8"


def test_aktif_profil_auto_ram16(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _motor_kur(monkeypatch, tmp_path, ["ram8", "ram16"])
    monkeypatch.delenv("YT_LLAMACPP_PROFIL", raising=False)
    monkeypatch.setattr("ytcore.config.fiziksel_ram_gb", lambda: 64.0)
    assert llamacpp.aktif_profil() == "ram16"


def test_aktif_profil_buyuk_ram_ama_ram16_dosyasi_yok(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Paket-içi tutarlılık: installer'a yalnız ram8 gömülü (NSIS sınırı). 127GB makinede
    bile ram16 dosyaları pakette yoksa auto ram8'e DÜŞMELI (eksik 12B'ye koşmamalı)."""
    _motor_kur(monkeypatch, tmp_path, ["ram8"])
    monkeypatch.delenv("YT_LLAMACPP_PROFIL", raising=False)
    monkeypatch.setattr("ytcore.config.fiziksel_ram_gb", lambda: 127.0)
    assert llamacpp.aktif_profil() == "ram8"


def test_aktif_profil_acik_secim_dosyaya_bakmaz(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Env/ayar ile açık profil seçimi dosya varlığına bakılmaksızın uygulanır —
    eksik dosya hatası _model_yolu'nda net biçimde yüzeye çıkar."""
    _motor_kur(monkeypatch, tmp_path, ["ram8"])
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram16")
    assert llamacpp.aktif_profil() == "ram16"


def test_profil_env_oncelikli(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram16")
    assert get_config().llamacpp_profil == "ram16"


def test_profil_varsayilan_auto(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("YT_LLAMACPP_PROFIL", raising=False)
    assert get_config().llamacpp_profil == "auto"


def test_backend_auto_motor_yoksa_ollama(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("YT_MOTOR_BACKEND", "auto")
    # Repo vendor dizini artık GÖMÜLÜ motorla dolu olabilir (geliştirme makinesi) —
    # bu test seçim mantığını kilitler; yol taraması ayrı testlerde.
    monkeypatch.setattr("ytcore.config.llamacpp_motor_kok", lambda: None)
    assert get_config().motor_backend == "ollama"


def test_backend_auto_gomulu_motor_varsa_llamacpp(monkeypatch: pytest.MonkeyPatch, tmp_path):
    (tmp_path / "modeller").mkdir()
    monkeypatch.setenv("RASATHANE_MOTOR_DIR", str(tmp_path))
    monkeypatch.setenv("YT_MOTOR_BACKEND", "auto")
    assert get_config().motor_backend == "llamacpp"


def test_backend_acik_secim(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_MOTOR_BACKEND", "llamacpp")
    assert get_config().motor_backend == "llamacpp"
    monkeypatch.setenv("YT_MOTOR_BACKEND", "OLLAMA")
    assert get_config().motor_backend == "ollama"


# --- KVKK fail-closed (#1) ----------------------------------------------------


def test_llamacpp_host_loopback_degilse_reddedilir(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_LLAMACPP_HOST", "http://192.168.1.50:8077")
    monkeypatch.delenv("YT_ALLOW_REMOTE_OLLAMA", raising=False)
    with pytest.raises(ValueError, match="KVKK fail-closed"):
        get_config()


def test_llamacpp_embed_host_loopback_degilse_reddedilir(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_LLAMACPP_EMBED_HOST", "http://10.0.0.9:8091")
    monkeypatch.delenv("YT_ALLOW_REMOTE_OLLAMA", raising=False)
    with pytest.raises(ValueError, match="KVKK fail-closed"):
        get_config()


# --- mesaj hazırlama (Gemma system-rolü desteklemez) ---------------------------


def test_gemma_system_prompt_kullanici_turuna_katlanir():
    mesajlar = llamacpp._mesajlari_hazirla("SISTEM KURALLARI", "icerik", "gemma-4-E4B.gguf")
    assert len(mesajlar) == 1
    assert mesajlar[0]["role"] == "user"
    assert "SISTEM KURALLARI" in mesajlar[0]["content"]
    assert "icerik" in mesajlar[0]["content"]


def test_diger_modellerde_roller_korunur():
    mesajlar = llamacpp._mesajlari_hazirla("sistem", "icerik", "qwen2.5-3b.gguf")
    assert [m["role"] for m in mesajlar] == ["system", "user"]


# --- istemci kontratı (stub sunucu) -------------------------------------------


def test_llm_uret_openai_kontrati(monkeypatch: pytest.MonkeyPatch, stub_sunucu):
    monkeypatch.setenv("YT_LLAMACPP_HOST", _stub_url(stub_sunucu))
    istemci = llamacpp.LlamaCppLLM()
    assert istemci.uret("sistem", "kullanici") == "stub yanit"
    yol, istek = stub_sunucu.kayitlar[-1]  # type: ignore[attr-defined]
    assert yol == "/v1/chat/completions"
    assert istek["temperature"] == 0.2
    assert istek["messages"][0]["role"] == "user"  # default profil gemma → katlanmış
    # Gemma 4 reasoning modeli — thinking kapalı gönderilmeli (yoksa content boş döner)
    assert istek["chat_template_kwargs"] == {"enable_thinking": False}


def test_embedding_sira_ve_batch(monkeypatch: pytest.MonkeyPatch, stub_sunucu):
    stub_sunucu.model_id = str(llamacpp.profil_bilgisi()["embed_dosya"])
    monkeypatch.setenv("YT_LLAMACPP_EMBED_HOST", _stub_url(stub_sunucu))
    saglayici = llamacpp.LlamaCppEmbedding()
    metinler = [f"metin {i}" for i in range(70)]  # 32'li batch → 3 istek
    vektorler = saglayici.embed(metinler)
    assert len(vektorler) == 70
    # index'e göre sıralandı: her öğenin embedding'i [batch-içi index, 1.0, 0.5] olmalı
    assert vektorler[0] == [0.0, 1.0, 0.5]
    assert vektorler[33] == [1.0, 1.0, 0.5]  # 2. batch'in 1. öğesi (ters kayıt düzeltilmiş)
    gomme_istekleri = [k for k in stub_sunucu.kayitlar if k[0] == "/v1/embeddings"]  # type: ignore[attr-defined]
    assert len(gomme_istekleri) == 3


def test_embedding_bos_liste(stub_sunucu):
    assert llamacpp.LlamaCppEmbedding(host=_stub_url(stub_sunucu)).embed([]) == []


def test_uret_ollama_model_adiyla_bile_gemma_katlamasi(
    monkeypatch: pytest.MonkeyPatch, stub_sunucu
):
    """2026-08-24 saha dersi: node'lar llamacpp backend'inde Ollama model adı geçirir
    (config reuse — 'qwen2.5:14b'). Katlama kararı istekteki ada bakarsa 'gemma' bulunamaz
    → system rolü sızar (Gemma template uyumsuzluğu riski). Karar SUNUCUDA YÜKLÜ profile
    bakmalı → llamacpp'te her zaman Gemma katlaması."""
    monkeypatch.setenv("YT_LLAMACPP_HOST", _stub_url(stub_sunucu))
    monkeypatch.delenv("RASATHANE_MOTOR_DIR", raising=False)
    istemci = llamacpp.LlamaCppLLM(model="qwen2.5:14b")
    assert istemci.uret("SISTEM", "icerik", model="qwen2.5:14b") == "stub yanit"
    _, istek = stub_sunucu.kayitlar[-1]  # type: ignore[attr-defined]
    # İstekteki model adı korunur (log/teşhis için) ama mesajlar katlanmış:
    assert istek["model"] == "qwen2.5:14b"
    assert len(istek["messages"]) == 1
    assert istek["messages"][0]["role"] == "user"
    assert "SISTEM" in istek["messages"][0]["content"]


def test_embedding_uzun_metin_chunk_ortalamasi(monkeypatch: pytest.MonkeyPatch, stub_sunucu):
    """Tam-gövde embed (~6K karakter) bge-m3 Q4 sunucuda HTTP 500 üretiyordu (paketli saha
    hatası) → degerleme düştü, index'e ekleme hiç koşmadı. Uzun metin _CHUNK_KAR'da parçalanır;
    dönen vektör parçaların ORTALAMASI (kontrat: N metin → N vektör)."""
    stub_sunucu.model_id = str(llamacpp.profil_bilgisi()["embed_dosya"])
    monkeypatch.setenv("YT_LLAMACPP_EMBED_HOST", _stub_url(stub_sunucu))
    saglayici = llamacpp.LlamaCppEmbedding()
    uzun = "a" * 2500  # boşluksuz → sert kesim: 1024 + 1024 + 452 = 3 parça
    vektorler = saglayici.embed([uzun])
    assert len(vektorler) == 1
    # Stub her parçaya [batch_içi_index, 1.0, 0.5] döndürür → ortalama [1.0, 1.0, 0.5]
    assert vektorler[0] == [1.0, 1.0, 0.5]
    gomme = [k for k in stub_sunucu.kayitlar if k[0] == "/v1/embeddings"]  # type: ignore[attr-defined]
    assert len(gomme) == 1  # 3 parça tek batch'te
    assert len(gomme[0][1]["input"]) == 3
    assert all(len(p) <= llamacpp.LlamaCppEmbedding._CHUNK_KAR for p in gomme[0][1]["input"])


def test_embedding_kisa_metin_tek_parcada(monkeypatch: pytest.MonkeyPatch, stub_sunucu):
    """Kısa metinler chunk'lanmaz (mevcut davranış birebir korunur)."""
    stub_sunucu.model_id = str(llamacpp.profil_bilgisi()["embed_dosya"])
    monkeypatch.setenv("YT_LLAMACPP_EMBED_HOST", _stub_url(stub_sunucu))
    saglayici = llamacpp.LlamaCppEmbedding()
    vektorler = saglayici.embed(["kısa metin"])
    assert vektorler == [[0.0, 1.0, 0.5]]
    gomme = [k for k in stub_sunucu.kayitlar if k[0] == "/v1/embeddings"]  # type: ignore[attr-defined]
    assert gomme[0][1]["input"] == ["kısa metin"]


def test_embedding_bos_metin_kontrati(monkeypatch: pytest.MonkeyPatch, stub_sunucu):
    """Boş/whitespace metin de bir vektör borçludur (N→N kontratı; çağıran zip bozulmaz)."""
    stub_sunucu.model_id = str(llamacpp.profil_bilgisi()["embed_dosya"])
    monkeypatch.setenv("YT_LLAMACPP_EMBED_HOST", _stub_url(stub_sunucu))
    vektorler = llamacpp.LlamaCppEmbedding().embed(["", "dolgu metni yeterince uzun"])
    assert len(vektorler) == 2


def test_parcala_kelime_sinirinda_keser():
    p = llamacpp.LlamaCppEmbedding._parcala(("kelime " * 400).strip())  # 2799 kar → parçalı
    assert len(p) > 1
    assert all(len(x) <= llamacpp.LlamaCppEmbedding._CHUNK_KAR for x in p)
    assert all(not x.startswith(" ") and not x.endswith(" ") for x in p)
    # Kelime ortası kesme yok: her parça tam kelimelerden oluşur
    assert all(all(k == "kelime" for k in x.split()) for x in p)


# --- motor raporu (kullanıcı isteği 2026-08-24: model/araç kökeni görünür) ------------------


def test_motor_raporu_llamacpp(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _motor_kur(monkeypatch, tmp_path, ["ram8"])
    monkeypatch.setenv("YT_MOTOR_BACKEND", "llamacpp")
    monkeypatch.setenv("YT_LLAMACPP_HOST", "http://127.0.0.1:9")  # kapalı → saglikli False
    monkeypatch.setenv("YT_LLAMACPP_EMBED_HOST", "http://127.0.0.1:9")
    rapor = llamacpp.motor_raporu()
    assert rapor["backend"] == "llamacpp"
    assert rapor["profil"] == "ram8"
    assert rapor["llm_model"] == "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
    assert rapor["embedding_model"] == "bge-m3-Q4_K_M.gguf"
    assert rapor["num_ctx"] == 4096
    assert rapor["llm_saglikli"] is False and rapor["embed_saglikli"] is False


def test_motor_raporu_ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_MOTOR_BACKEND", "ollama")
    rapor = llamacpp.motor_raporu()
    assert rapor["backend"] == "ollama"
    assert rapor["llm_model"] == "qwen2.5:14b"
    assert rapor["embedding_model"] == "bge-m3"


# --- sunucu yaşam döngüsü -------------------------------------------------------


def test_saglik_sorgusu_kapali_porta_false():
    assert llamacpp.sunucu_saglikli_mi("http://127.0.0.1:9") is False


def test_model_yolu_dosya_yoksa_acik_hata(monkeypatch: pytest.MonkeyPatch, tmp_path):
    (tmp_path / "modeller").mkdir()
    monkeypatch.setenv("RASATHANE_MOTOR_DIR", str(tmp_path))
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram8")
    with pytest.raises(FileNotFoundError, match="fetch-motor.ps1"):
        llamacpp._model_yolu("llm")


def test_model_yolu_bulunur(monkeypatch: pytest.MonkeyPatch, tmp_path):
    modeller = tmp_path / "modeller"
    modeller.mkdir()
    ad = str(llamacpp.PROFILLER["ram16"]["llm_dosya"])
    (modeller / ad).write_bytes(b"gguf")
    monkeypatch.setenv("RASATHANE_MOTOR_DIR", str(tmp_path))
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram16")
    assert llamacpp._model_yolu("llm").name == ad


def test_profil_bilgisi_bilinmeyen():
    with pytest.raises(ValueError, match="profil"):
        llamacpp.profil_bilgisi("ram64")


class _Process:
    def __init__(self):
        self.returncode = None
        self.terminated = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = 0

    def wait(self, timeout):
        return self.returncode


@pytest.fixture
def lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _motor_kur(monkeypatch, tmp_path, ["ram8", "ram16"])
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram8")
    monkeypatch.setenv("YT_LLAMACPP_HOST", "http://127.0.0.1:8077")
    monkeypatch.setattr(llamacpp, "_prosesler", {})
    monkeypatch.setattr(llamacpp, "_aktif_hostlar", {})
    monkeypatch.setattr(llamacpp, "_log_handlelari", {})
    monkeypatch.setattr(llamacpp, "_model_fingerprints", {})
    monkeypatch.setattr(llamacpp, "_son_kullanilan_modeller", {})
    monkeypatch.setattr(llamacpp, "_sunucu_bin", lambda: tmp_path / "llama-server.exe")
    monkeypatch.setattr(llamacpp, "_sunucu_log_yolu", lambda tur: None)
    monkeypatch.setattr("ytcore.local.resources.require_memory", lambda size: None)
    return tmp_path


def test_foreign_healthy_model_is_verified_over_models_api(
    monkeypatch: pytest.MonkeyPatch, stub_sunucu
):
    monkeypatch.setenv("YT_LLAMACPP_HOST", _stub_url(stub_sunucu))
    assert llamacpp.sunucu_baslat_gerekirse("llm") == _stub_url(stub_sunucu)
    provenance = llamacpp.motor_raporu()["llm_koken"]
    assert provenance["verified_model_id"] == stub_sunucu.model_id
    assert provenance["ownership"] == "external"
    assert provenance["num_ctx_verified"] is None


@pytest.mark.parametrize("change", ["profile", "file"])
def test_owned_model_fingerprint_change_restarts_before_reuse(
    monkeypatch: pytest.MonkeyPatch, lifecycle, change
):
    process = _Process()
    old_host = "http://127.0.0.1:8077"
    llamacpp._prosesler["llm"] = process
    llamacpp._aktif_hostlar["llm"] = old_host
    llamacpp._model_fingerprints["llm"] = llamacpp._model_fingerprint("llm")
    if change == "profile":
        monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram16")
    else:
        llamacpp._model_yolu("llm").write_bytes(b"replacement-gguf")
    calls = []

    def spawn(command, **kwargs):
        calls.append(command)
        return _Process()

    monkeypatch.setattr(llamacpp.subprocess, "Popen", spawn)
    monkeypatch.setattr(llamacpp, "sunucu_saglikli_mi", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        llamacpp,
        "sunucu_model_kimligi",
        lambda *args, **kwargs: str(llamacpp.profil_bilgisi()["llm_dosya"]),
    )
    monkeypatch.setattr(llamacpp, "_bos_port_sec", lambda base: 8079)
    assert llamacpp.sunucu_baslat_gerekirse("llm") == "http://127.0.0.1:8079"
    assert process.terminated == 1
    assert len(calls) == 1
    assert calls[0][calls[0].index("--model") + 1] == str(llamacpp._model_yolu("llm"))
    assert llamacpp._model_fingerprints["llm"] == llamacpp._model_fingerprint("llm")


def test_ram8_unloads_owned_opposite_even_when_target_is_healthy(
    monkeypatch: pytest.MonkeyPatch, lifecycle, stub_sunucu
):
    process = _Process()
    llamacpp._prosesler["embed"] = process
    llamacpp._aktif_hostlar["embed"] = "http://127.0.0.1:8078"
    monkeypatch.setenv("YT_LLAMACPP_HOST", _stub_url(stub_sunucu))
    assert llamacpp.sunucu_baslat_gerekirse("llm") == _stub_url(stub_sunucu)
    assert process.terminated == 1
    assert "embed" not in llamacpp._prosesler


def test_unknown_foreign_healthy_model_uses_free_port_without_killing_it(
    monkeypatch: pytest.MonkeyPatch, lifecycle, stub_sunucu
):
    stub_sunucu.model_id = "unrelated-model.gguf"
    foreign_host = _stub_url(stub_sunucu)
    monkeypatch.setenv("YT_LLAMACPP_HOST", foreign_host)
    owned = _Process()
    commands = []

    def spawn(command, **kwargs):
        commands.append(command)
        return owned

    monkeypatch.setattr(llamacpp.subprocess, "Popen", spawn)
    monkeypatch.setattr(llamacpp, "_bos_port_sec", lambda base: 8079)
    original_health = llamacpp.sunucu_saglikli_mi
    original_identity = llamacpp.sunucu_model_kimligi
    monkeypatch.setattr(
        llamacpp,
        "sunucu_saglikli_mi",
        lambda host, **kwargs: host.endswith(":8079") or original_health(host),
    )
    monkeypatch.setattr(
        llamacpp,
        "sunucu_model_kimligi",
        lambda host, **kwargs: (
            str(llamacpp.profil_bilgisi()["llm_dosya"])
            if host.endswith(":8079")
            else original_identity(host)
        ),
    )
    assert llamacpp.sunucu_baslat_gerekirse("llm") == "http://127.0.0.1:8079"
    assert original_health(foreign_host)
    assert original_identity(foreign_host) == "unrelated-model.gguf"
    assert owned.terminated == 0 and len(commands) == 1


def test_owned_starting_process_waits_for_verified_ready_model(monkeypatch, lifecycle):
    process = _Process()
    llamacpp._prosesler["llm"] = process
    llamacpp._aktif_hostlar["llm"] = "http://127.0.0.1:8077"
    llamacpp._model_fingerprints["llm"] = llamacpp._model_fingerprint("llm")
    health = iter((False, False, True))
    monkeypatch.setattr(llamacpp, "sunucu_saglikli_mi", lambda host: next(health))
    identity_calls = []

    def identity(host):
        identity_calls.append(host)
        return str(llamacpp.profil_bilgisi()["llm_dosya"])

    monkeypatch.setattr(llamacpp, "sunucu_model_kimligi", identity)
    monkeypatch.setattr(llamacpp.time, "sleep", lambda duration: None)
    assert llamacpp.sunucu_baslat_gerekirse("llm") == "http://127.0.0.1:8077"
    assert identity_calls == ["http://127.0.0.1:8077"]
    assert process.terminated == 0


def test_opposite_model_waits_until_inference_finishes(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    embed_attempted = threading.Event()
    embed_loaded = threading.Event()
    order = []
    results = []

    def start(kind):
        order.append(kind + "-load")
        if kind == "embed":
            embed_loaded.set()
        return "http://127.0.0.1:8077"

    def post(url, **kwargs):
        order.append("chat-enter")
        entered.set()
        assert release.wait(5)
        order.append("chat-exit")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "result"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llamacpp, "sunucu_baslat_gerekirse", start)
    monkeypatch.setattr(llamacpp.httpx, "post", post)
    monkeypatch.setattr(llamacpp.LlamaCppEmbedding, "_gonder", lambda *args: [[1.0]])
    llm = threading.Thread(target=lambda: results.append(llamacpp.LlamaCppLLM().uret("s", "u")))

    def embed():
        embed_attempted.set()
        results.append(llamacpp.LlamaCppEmbedding().embed(["metin"]))

    embedding = threading.Thread(target=embed)
    llm.start()
    assert entered.wait(5)
    embedding.start()
    try:
        assert embed_attempted.wait(5)
        assert not embed_loaded.wait(0.1)
    finally:
        release.set()
        llm.join(5)
        embedding.join(5)
    assert order == ["llm-load", "chat-enter", "chat-exit", "embed-load"]
    assert results == ["result", [[1.0]]]
