from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

from ytcore.config import get_config
from ytcore.models import AnalizSonucu
from ytcore.output.git_commit import analiz_commit_guvenli
from ytcore.pipeline.checkpoint import get_checkpointer
from ytcore.pipeline.graph import graph_olustur

ANALYSIS_LOCK = threading.RLock()


class AnalysisCancelled(RuntimeError):
    """İptal edilmiş iş bir sonraki graph node'una geçmez."""


def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise AnalysisCancelled("Analiz kullanıcı tarafından iptal edildi.")


def kaynak_analiz_et(
    url: str,
    konu: str = "genel",
    thread_id: str = "varsayilan",
    checkpoint_dir: Path | None = None,
    asr_izin: bool = False,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
    profile: str | None = None,
    output_run_id: str | None = None,
) -> AnalizSonucu:
    """Public giriş: desteklenen bir URL'yi ortak Rasathane hattında analiz eder.

    YouTube altyazı/ASR edinimini korur; GitHub, arXiv, Reddit, Hugging Face ve web
    adapter belgelerini aynı PII/routing/özet/zeka/çıktı graph'ına taşır. YouTube'da
    altyazı yoksa `asr_izin=True` verilmeden sessiz Whisper fallback yapılmaz.
    Her çağrı aynı db'de taze checkpointer yaratır; thread_id state diske persist
    edilir (`get_state` ile okunabilir). NOT: bu public yol her çağrıda grafı baştan
    çalıştırır (iş-devamı=resume DEĞİL — yarım kalan pahalı ASR'ı tekrar koşar);
    gerçek iş-devamı batch-worker'da (Faz 2+) `invoke(None)` ile gelecek. Çıktı
    output_base bir git repo ise analiz-başına commit edilir (değilse graceful skip).
    Ürün işleri output_run_id ile değişmez bir çıktı klasörü alır; ortak index/bellek
    aynı kökte kalır. Parametre verilmeyen legacy çağrıların klasör düzeni korunur.
    """
    # Engine config'in eski env contract'ı yalnız ortak mutex içinde snapshot edilir.
    # GUI, MCP ve ürün job'u aynı kilidi kullanır; 8GB cihazda iki graph aynı anda model
    # çalıştırmaz. İptal bir devam eden HTTP/model çağrısını zorla kesmez, node sınırındadır.
    while not ANALYSIS_LOCK.acquire(timeout=0.2):
        _check_cancel(cancel_check)
    old_profile = os.environ.get("YT_LLAMACPP_PROFIL")
    try:
        _check_cancel(cancel_check)
        if output_run_id is not None and not re.fullmatch(r"[a-f0-9]{32}", output_run_id):
            raise ValueError("Geçersiz output run kimliği.")
        if profile is not None:
            if profile not in {"ram8", "ram16", "auto"}:
                raise ValueError("Geçersiz analiz profili.")
            os.environ["YT_LLAMACPP_PROFIL"] = profile
        return _kaynak_analiz_kilitli(
            url, konu, thread_id, checkpoint_dir, asr_izin, cancel_check, progress, output_run_id
        )
    finally:
        if old_profile is None:
            os.environ.pop("YT_LLAMACPP_PROFIL", None)
        else:
            os.environ["YT_LLAMACPP_PROFIL"] = old_profile
        ANALYSIS_LOCK.release()


def _kaynak_analiz_kilitli(
    url: str,
    konu: str,
    thread_id: str,
    checkpoint_dir: Path | None,
    asr_izin: bool,
    cancel_check: Callable[[], bool] | None,
    progress: Callable[[str], None] | None,
    output_run_id: str | None,
) -> AnalizSonucu:
    cp_dir = checkpoint_dir or (Path.home() / ".ytanaliz")
    checkpointer = get_checkpointer(cp_dir / "checkpoints.sqlite")
    try:
        app = graph_olustur(checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        initial: dict[str, object] = {
            "url": url,
            "konu": konu,
            "asr_izin": asr_izin,
            "output_run_id": output_run_id,
        }
        if cancel_check is None and progress is None:
            son = app.invoke(initial, config=config)
        else:
            stream = app.stream(
                initial,
                config=config,
                stream_mode="updates",
            )
            try:
                for update in stream:
                    _check_cancel(cancel_check)
                    if progress:
                        for stage in update:
                            progress(str(stage))
                    _check_cancel(cancel_check)
                son = app.get_state(config).values
            finally:
                stream.close()
        _check_cancel(cancel_check)
        sonuc = AnalizSonucu.model_validate(son["sonuc"])
        mesaj = f"analiz: {sonuc.index.konu}/{sonuc.index.video_slug}"
        sonuc.commit_yapildi = analiz_commit_guvenli(
            get_config().output_base, Path(sonuc.klasor), mesaj
        )
        return sonuc
    finally:
        # Windows: açık SQLite handle dosya silmeyi engeller (exe teardown dersi).
        checkpointer.conn.close()


def analiz_et(
    url: str,
    konu: str = "genel",
    thread_id: str = "varsayilan",
    checkpoint_dir: Path | None = None,
    asr_izin: bool = False,
) -> AnalizSonucu:
    """Geriye uyumlu ad; yeni kod `kaynak_analiz_et` kullanabilir."""
    return kaynak_analiz_et(
        url=url,
        konu=konu,
        thread_id=thread_id,
        checkpoint_dir=checkpoint_dir,
        asr_izin=asr_izin,
    )
