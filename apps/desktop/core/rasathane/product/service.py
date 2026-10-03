from __future__ import annotations

import atexit
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rasathane.product.connectors import fetch_feed, muhakeme_configured
from rasathane.product.research_chat import answer_from_sources, local_results
from rasathane.product.store import ProductStore
from rasathane.product.web import (
    SearchProvider,
    fetch_preview,
    search_provider,
    validate_public_url,
)

AnalysisEngine = Callable[
    [dict[str, Any], Callable[[], bool], Callable[[str], None]], dict[str, Any]
]


class JobCancelled(RuntimeError):
    pass


class ProductService:
    """FIFO tek iş; kalıcı durum; yalnız uygulama açıkken topic timer."""

    def __init__(
        self,
        store: ProductStore,
        *,
        search: SearchProvider | None = None,
        fetch: Callable[[str], dict[str, Any]] | None = None,
        analysis: AnalysisEngine | None = None,
        autostart: bool = True,
    ) -> None:
        self.store, self.search_override = store, search
        self.fetch = fetch or fetch_preview
        self.analysis = analysis or self._engine_analysis
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._run_lock = threading.Lock()
        self._native_authenticated = threading.Event()
        if autostart:
            self.ensure_official_feeds()
            self.store.recover_interrupted()
            self._worker = threading.Thread(
                target=self._loop, name="rasathane-product", daemon=True
            )
            self._worker.start()
            atexit.register(self.stop)

    def ensure_official_feeds(self) -> None:
        # Varsayılanlar fixture içerik değildir: public kaynak yapılandırmasıdır.
        # Makaleler yalnız başarılı gerçek fetch sonrası gelir. Kullanıcının kapattığı
        # kaynağı yeniden açma veya kendi metadata'sını değiştirme.
        kinds = {row["kind"] for row in self.store.list_feeds()}
        for name, url, kind in (
            ("Resmî Gazete", "https://www.resmigazete.gov.tr/", "resmi_gazete"),
            (
                "Yargıtay · kamuya açık karar künyeleri",
                "https://mevzuat.adalet.gov.tr/",
                "yargitay_public",
            ),
        ):
            if kind not in kinds:
                self.store.upsert_feed(
                    name,
                    url,
                    kind,
                    {
                        "fetch_interval_minutes": 360 if kind == "yargitay_public" else 180,
                    },
                )

    def submit(self, kind: str, request: dict[str, Any]) -> dict[str, Any]:
        if kind not in {"analysis", "research", "refresh", "feed_refresh"}:
            raise ValueError("Desteklenmeyen iş türü.")
        frozen = {**request, "settings": self.store.settings()}
        if kind == "refresh" and not frozen["settings"]["web_enabled"]:
            raise ValueError("Web araması kapalı; konu kaynakları yenilenemedi.")
        if kind == "analysis":
            frozen["url"] = validate_public_url(request.get("url", ""))
        if kind in {"research", "refresh"} and request.get("workspace_id"):
            if not any(
                row["id"] == request["workspace_id"] for row in self.store.list_workspaces()
            ):
                raise ValueError("Çalışma alanı bulunamadı.")
        if kind == "research" and not str(request.get("query", "")).strip():
            raise ValueError("Arama sorgusu boş olamaz.")
        job = self.store.enqueue(kind, frozen)
        self._wake.set()
        return job

    def set_native_authenticated(self, authenticated: bool) -> None:
        if authenticated:
            self._native_authenticated.set()
            self._wake.set()
        else:
            self._native_authenticated.clear()
            self.store.cancel_pending_jobs()

    def _session_ready(self) -> bool:
        # CLI/test mode has no native session. Packaged workers stay idle until
        # Electron main has refreshed and supplied a valid account access token.
        return not os.environ.get("RASATHANE_SESSION_TOKEN") or self._native_authenticated.is_set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self._schedule()
                self._wake.wait(2)
                self._wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout=2)

    def _schedule(self) -> None:
        if not self._session_ready():
            return
        settings = self.store.settings()
        minutes = settings["topic_refresh_minutes"]
        pending_source_jobs = self.store.rows(
            "SELECT request FROM jobs WHERE kind='feed_refresh' "
            "AND status IN ('queued','running','cancel_requested')"
        )
        for feed in self.store.list_feeds():
            if not feed["enabled"] or not feed["supported"]:
                continue
            if any(
                job["request"].get("source_id") in {None, feed["id"]} for job in pending_source_jobs
            ):
                continue
            last = feed["last_refreshed_at"]
            meta = feed["metadata"]
            next_attempt = meta.get("next_attempt_at")
            if next_attempt and datetime.fromisoformat(next_attempt) > datetime.now(UTC):
                continue
            minimum = (
                360
                if feed["kind"] == "yargitay_public"
                else (180 if feed["kind"] == "resmi_gazete" else 15)
            )
            try:
                interval = max(minimum, min(10080, int(meta.get("fetch_interval_minutes", 180))))
            except (ValueError, TypeError):
                interval = max(minimum, 180)
            if (
                not last
                or (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds()
                >= interval * 60
            ):
                self.submit("feed_refresh", {"source_id": feed["id"], "automatic": True})
        # Web search and topic timing are independent of subscribed publisher feeds.
        if not minutes or not settings["web_enabled"]:
            return
        pending = {
            job["request"].get("topic_id")
            for job in self.store.list_jobs(brief=True)
            if job["status"] in {"queued", "running", "cancel_requested"}
        }
        # Hatalı provider'ı iki saniyede bir tekrar çağırma. Son başarısız/manual işin
        # zamanı da aralık bütçesine girer; last_success değerini değiştirip yeşile boyamaz.
        attempts: dict[str, str] = {}
        for job in self.store.list_jobs(brief=True):
            topic_id = job["request"].get("topic_id")
            if topic_id and topic_id not in attempts:
                attempts[topic_id] = job["created_at"]
        for topic in self.store.list_topics():
            if not topic["enabled"] or topic["id"] in pending:
                continue
            previous = topic["last_refreshed_at"]
            if attempt := attempts.get(topic["id"]):
                if (
                    datetime.now(UTC) - datetime.fromisoformat(attempt)
                ).total_seconds() < minutes * 60:
                    continue
            # Yeni topic ilk manuel yenilemesini bekler; ayar oluşturmak ağ çağrısı yapmaz.
            if (
                previous
                and (datetime.now(UTC) - datetime.fromisoformat(previous)).total_seconds()
                >= minutes * 60
            ):
                self.submit("refresh", {"topic_id": topic["id"]})

    def run_once(self) -> bool:
        if not self._session_ready():
            return False
        if not self._run_lock.acquire(blocking=False):
            return False
        job = None
        try:
            job = self.store.claim_next()
            if job is None:
                return False

            def cancelled() -> bool:
                return (
                    self._stop.is_set()
                    or not self._session_ready()
                    or self.store.get_job(job["id"])["cancel_requested"]
                )

            def check() -> None:
                if cancelled():
                    raise JobCancelled("İş kullanıcı tarafından iptal edildi.")

            def progress(stage: str) -> None:
                check()
                self.store.update_job(job["id"], stage=stage)

            check()
            request = job["request"]
            if job["kind"] == "analysis":
                result = self.analysis({**request, "job_id": job["id"]}, cancelled, progress)
                check()
                if result.get("transkript_durumu") == "hata":
                    # Engine hata makbuzunu sakla; okunamayan kaynak tamamlanmış analiz
                    # veya kütüphane içeriği olarak gösterilmesin.
                    self.store.update_job(
                        job["id"],
                        "failed",
                        result=result,
                        error=result.get("transkript_hata") or "Kaynak metni edinilemedi.",
                    )
                    return True
                self.store.add_analysis(job["id"], result)
            elif job["kind"] == "research":
                result = self._research(request, check, progress)
                progress("answer_compose")
                previous = []
                conversation_id = request.get("conversation_id")
                if conversation_id:
                    previous = self.store.latest_conversation_citations(conversation_id)
                result.update(answer_from_sources(result, previous))
                result.update(conversation_id=conversation_id, turn_id=request.get("turn_id"))
            elif job["kind"] == "refresh":
                topic = next(
                    (row for row in self.store.list_topics() if row["id"] == request["topic_id"]),
                    None,
                )
                if topic is None:
                    raise ValueError("Konu takibi bulunamadı.")
                result = self._research(
                    {**request, "query": topic["query"], "web": True}, check, progress
                )
                check()
                if result["status"] in {"local_only", "web_blocked_pii"} or (
                    result["errors"] and not result["web_results"]
                ):
                    raise RuntimeError(
                        result["errors"][0]
                        if result["errors"]
                        else "Konu için web kaynakları yenilenemedi."
                    )
                result["topic_id"] = topic["id"]
                result["new_count"] = self.store.record_topic_hits(
                    topic["id"], result["web_results"]
                )
            else:
                result = self._feed_refresh(request, check, progress)
            check()
            self.store.update_job(job["id"], "completed", result=result)
            return True
        except Exception as exc:
            if job:
                from ytcore.pipeline.api import AnalysisCancelled

                is_cancel = (
                    isinstance(exc, (JobCancelled, AnalysisCancelled))
                    or self.store.get_job(job["id"])["cancel_requested"]
                )
                status = (
                    "cancelled"
                    if is_cancel
                    else ("interrupted" if self._stop.is_set() else "failed")
                )
                self.store.update_job(
                    job["id"],
                    status,
                    error="İş iptal edildi."
                    if is_cancel
                    else f"{type(exc).__name__}: {str(exc)[:500]}",
                )
                if job["kind"] == "refresh" and not is_cancel:
                    self.store.topic_error(job["request"]["topic_id"], str(exc))
            return job is not None
        finally:
            self._run_lock.release()

    def _provider(self, settings: dict[str, Any]) -> SearchProvider:
        return self.search_override or search_provider(settings.get("search_provider", "auto"))

    def _research(
        self, request: dict[str, Any], check: Callable[[], None], progress: Callable[[str], None]
    ) -> dict[str, Any]:
        query, workspace_id = request["query"], request.get("workspace_id")
        progress("local_search")
        result: dict[str, Any] = {
            "query": query,
            "workspace_id": workspace_id,
            "local_results": local_results(self.store, query, workspace_id),
            "web_results": [],
            "provider": "local",
            "status": "completed",
            "errors": [],
        }
        settings = request.get("settings") or self.store.settings()
        if not request.get("web", True) or not settings["web_enabled"]:
            result["status"] = "local_only"
            return result
        # Sorgu kaynağın tamamı değildir ama kişi/veri çıkışı olabilir: tüm sağlayıcılara
        # regex+NER egress gate uygulanır. Fail-closed NER eksikse yerel arama çalışır.
        if self.search_override is None:
            from ytcore.router.ner import ner_al
            from ytcore.router.pii_gate import pii_iceriyor_mu

            if pii_iceriyor_mu(query).var or any(ner_al().kisi_var_mi([query])):
                result["status"] = "web_blocked_pii"
                result["errors"].append(
                    "Sorgu kişi verisi içeriyor veya NER güvenle doğrulanamadı; "
                    "yalnız yerel arama yapıldı."
                )
                return result
        provider = self._provider(settings)
        result["provider"] = provider.name
        progress("web_search")
        hits = provider.search(query, 5)
        for hit in hits[:5]:
            check()
            try:
                url = validate_public_url(hit["url"])
            except ValueError as exc:
                result["errors"].append(str(exc))
                continue
            progress("source_fetch")
            body, status, provenance = hit.get("excerpt", ""), "snippet_only", {}
            try:
                page = self.fetch(url)
                check()
                body, status = page.get("body", "")[:20_000], "saved_preview"
                provenance = page.get("provenance", {})
            except JobCancelled:
                raise
            except Exception as exc:
                result["errors"].append(f"{url}: {str(exc)[:200]}")
            check()
            saved = self.store.save_web_source(
                workspace_id,
                url,
                hit.get("title") or url,
                body,
                provider.name,
                query=query,
                provenance={**provenance, "fetch_status": status},
            )
            result["web_results"].append(
                {
                    "title": hit.get("title") or url,
                    "url": url,
                    "excerpt": hit.get("excerpt", ""),
                    "body": body,
                    "source_id": saved["source_id"],
                    "version_id": saved["version_id"],
                    "content_hash": saved["content_hash"],
                    "fetch_status": status,
                    "retrieved_at": saved["retrieved_at"],
                }
            )
        if result["errors"]:
            result["status"] = "partial"
        return result

    def _feed_refresh(
        self, request: dict[str, Any], check: Callable[[], None], progress: Callable[[str], None]
    ) -> dict[str, Any]:
        feed_id = request.get("source_id")
        feeds = [row for row in self.store.list_feeds() if feed_id is None or row["id"] == feed_id]
        if feed_id and not feeds:
            raise ValueError("Kaynak bulunamadı.")
        result: dict[str, Any] = {"inserted": 0, "sources": [], "errors": [], "status": "completed"}
        for saved_feed in feeds:
            check()
            feed = self.store.get_feed(saved_feed["id"])
            if feed is None or not feed["enabled"]:
                result["sources"].append(
                    {"id": saved_feed["id"], "inserted": 0, "skipped": "paused_or_removed"}
                )
                continue
            if feed["kind"] in {"yargitay_public", "resmi_gazete"}:
                cache_minutes = 360 if feed["kind"] == "yargitay_public" else 180
                previous = feed["last_refreshed_at"]
                if (
                    previous
                    and not feed["last_error"]
                    and (datetime.now(UTC) - datetime.fromisoformat(previous)).total_seconds()
                    < cache_minutes * 60
                ):
                    result["sources"].append(
                        {
                            "id": feed["id"],
                            "inserted": 0,
                            "cached": True,
                            "last_refreshed_at": previous,
                        }
                    )
                    continue
            next_attempt = feed["metadata"].get("next_attempt_at")
            if next_attempt and datetime.fromisoformat(next_attempt) > datetime.now(UTC):
                result["errors"].append(
                    {
                        "id": feed["id"],
                        "error": "Kaynak bekleme aralığında.",
                        "retry_after": next_attempt,
                    }
                )
                continue
            if not self.store.begin_feed_attempt(feed):
                result["sources"].append(
                    {"id": feed["id"], "inserted": 0, "skipped": "configuration_changed"}
                )
                continue
            progress("feed_fetch")
            try:
                articles = fetch_feed(feed)
                check()
                count = self.store.finish_feed_attempt(feed, articles)
                if count is None:
                    result["sources"].append(
                        {"id": feed["id"], "inserted": 0, "skipped": "configuration_changed"}
                    )
                    continue
                result["inserted"] += count
                result["sources"].append({"id": feed["id"], "inserted": count})
            except JobCancelled:
                raise
            except Exception as exc:
                recorded = self.store.finish_feed_attempt(
                    feed, error=str(exc), delay_seconds=getattr(exc, "retry_after_seconds", 600)
                )
                if recorded is None:
                    result["sources"].append(
                        {"id": feed["id"], "inserted": 0, "skipped": "configuration_changed"}
                    )
                    continue
                result["errors"].append({"id": feed["id"], "error": str(exc)[:300]})
        if result["errors"]:
            result["status"] = "partial"
        if feeds and len(result["errors"]) == len(feeds):
            raise RuntimeError(
                "Hiçbir kaynak yenilenemedi; kaynakların hata ayrıntılarını kontrol edin."
            )
        return result

    def _engine_analysis(
        self,
        request: dict[str, Any],
        cancelled: Callable[[], bool],
        progress: Callable[[str], None],
    ) -> dict[str, Any]:
        from ytcore.pipeline.api import kaynak_analiz_et

        result = kaynak_analiz_et(
            request["url"],
            request.get("konu", "genel"),
            request["job_id"],
            self.store.directory / "checkpoints",
            bool(request.get("asr_izin", False)),
            cancel_check=cancelled,
            progress=progress,
            profile=request["settings"]["analysis_profile"],
            output_run_id=request["job_id"],
        ).model_dump()
        artifacts = []
        directory = Path(result["klasor"]).resolve()
        from ytcore.config import get_config

        if directory.is_relative_to(get_config().output_base.resolve()) and directory.is_dir():
            for path in directory.iterdir():
                if path.is_file() and path.suffix.lower() in {
                    ".md",
                    ".json",
                    ".wav",
                    ".mp3",
                    ".html",
                    ".pdf",
                    ".docx",
                }:
                    import hashlib

                    with path.open("rb") as handle:
                        content_hash = hashlib.file_digest(handle, "sha256").hexdigest()
                    artifacts.append(
                        {
                            "name": path.name,
                            "bytes": path.stat().st_size,
                            "sha256": content_hash,
                            "path": str(path),
                        }
                    )
        result["artifacts"] = artifacts
        return result

    def state(self) -> dict[str, Any]:
        bridge_configured = muhakeme_configured()
        return {
            "product": "Rasathane",
            "schema_version": 1,
            "counts": self.store.counts(),
            "sources": self.store.list_feeds(),
            "articles": self.store.list_articles(),
            "workspaces": self.store.list_workspaces(),
            "topics": self.store.list_topics(),
            "jobs": self.store.list_jobs(brief=True),
            "library": self.store.library(brief=True),
            "settings": self.store.settings(),
            "integrations": {
                "scheduler": "while_application_open",
                "official_sources": [
                    {
                        "kind": "resmi_gazete",
                        "name": "Resmî Gazete",
                        "source_link": "https://www.resmigazete.gov.tr/",
                        "status": "connector_available",
                    },
                    {
                        "kind": "yargitay_public",
                        "name": "Yargıtay · Adalet kamu arşivi",
                        "source_link": "https://mevzuat.adalet.gov.tr/",
                        "status": "connector_available",
                        "text_scope": "official_metadata",
                        "date_semantics": "decision_date_not_publication_date",
                    },
                    {
                        "kind": "yargitay",
                        "name": "Yargıtay özetleri · Muhakeme",
                        "source_link": "https://karararama.yargitay.gov.tr/",
                        "status": "configured_unverified"
                        if bridge_configured
                        else "not_configured",
                        "text_scope": "managed_summary",
                        "analysis_supported": False,
                    },
                    {
                        "kind": "mevzuat",
                        "name": "Mevzuat özetleri · Muhakeme",
                        "source_link": "https://www.mevzuat.gov.tr/",
                        "status": "configured_unverified"
                        if bridge_configured
                        else "not_configured",
                        "text_scope": "managed_summary",
                        "analysis_supported": False,
                    },
                ],
            },
        }
