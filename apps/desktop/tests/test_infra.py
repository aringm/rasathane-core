from __future__ import annotations

from ytcore.infra.embedding import EmbeddingProvider, get_embedding_provider
from ytcore.infra.index import IndexStore, get_index_store
from ytcore.infra.vram import VRAM_BUTCE, bge_m3_batch_guvenli


def test_vram_butce_16gb_siniri():
    assert VRAM_BUTCE["limit_gb"] == 16.0
    # bge-m3 batch-256 ~5.7GB (NOT 1.5) — global batch sınırı kuralı
    assert VRAM_BUTCE["bge_m3_batch256_gb"] == 5.7
    assert bge_m3_batch_guvenli(32) is True
    assert bge_m3_batch_guvenli(256) is False


def test_embedding_default_bge_m3():
    p = get_embedding_provider()
    assert isinstance(p, EmbeddingProvider)
    assert p.ad == "bge-m3"  # MIT lisans-net default


def test_index_store_iface():
    s = get_index_store()
    assert isinstance(s, IndexStore)


def test_whisperx_align_butce_kayitli():
    # Faz 1: WhisperX align modeli defterde + ayrı proses (≤16GB değişmez).
    assert "whisperx_align_gb" in VRAM_BUTCE
    assert VRAM_BUTCE["whisperx_align_gb"] < 2.0  # wav2vec2-300m
