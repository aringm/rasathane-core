from __future__ import annotations

import os
import threading
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from rasathane.product.connectors import set_service_session
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore
from rasathane.product.web import validate_public_url

_lock = threading.Lock()
_service: ProductService | None = None


def get_service() -> ProductService:
    global _service
    with _lock:
        if _service is None:
            _service = ProductService(ProductStore())
        return _service


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Analysis(Input):
    url: str = Field(min_length=1, max_length=2048)
    konu: str = Field(default="genel", min_length=1, max_length=100)
    asr_izin: StrictBool = False


class Research(Input):
    query: str = Field(min_length=1, max_length=500)
    workspace_id: str | None = Field(default=None, max_length=64)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    web: StrictBool = True


class Workspace(Input):
    name: str = Field(min_length=1, max_length=120)


class Bulletin(Input):
    article_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        min_length=1, max_length=20
    )
    title: str = Field(default="Akış bülteni", min_length=1, max_length=120)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=64)


class Note(Input):
    workspace_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(max_length=100_000)


class Topic(Input):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=500)


class Source(Input):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    kind: Literal[
        "rss",
        "arxiv",
        "reddit",
        "youtube_channel",
        "resmi_gazete",
        "yargitay_public",
        "yargitay",
        "mevzuat",
    ] = "rss"
    enabled: StrictBool = True
    category: str | None = Field(default=None, min_length=1, max_length=80)


class SourceUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    kind: (
        Literal[
            "rss",
            "arxiv",
            "reddit",
            "youtube_channel",
            "resmi_gazete",
            "yargitay_public",
            "yargitay",
            "mevzuat",
        ]
        | None
    ) = None
    enabled: StrictBool | None = None
    category: str | None = Field(default=None, min_length=1, max_length=80)


class ArticleQuery(Input):
    source_id: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=80)
    query: str | None = Field(default=None, max_length=500)
    days: int = Field(default=0, ge=0, le=36500)
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=10_000_000)


class Settings(Input):
    theme: Literal["dark", "light", "system"] | None = None
    web_enabled: StrictBool | None = None
    search_provider: Literal["auto", "duckduckgo", "configured"] | None = None
    analysis_profile: Literal["ram8", "ram16", "auto"] | None = None
    topic_refresh_minutes: StrictInt | None = Field(default=None, ge=0, le=10080)


class ServiceSession(Input):
    access_token: str | None = Field(pattern=r"^at_[A-Za-z0-9_-]{43}$")


async def _input(request: Request, model: type[Input]) -> dict[str, Any]:
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        raise ValueError("JSON Content-Type zorunlu.")
    raw = await request.body()
    if len(raw) > 200_000:
        raise ValueError("İstek gövdesi izin verilen boyutu aşıyor.")
    return model.model_validate_json(raw).model_dump(exclude_none=True)


def register_routes(mcp: FastMCP) -> None:
    @mcp.custom_route("/api/product/service-session", methods=["POST", "OPTIONS"])
    async def product_service_session(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        # Dev API'den de token girişi yok. Main private endpoint'i request IPC route
        # allowlist'inde bulunmaz; production middleware origin+session doğrular.
        if not os.environ.get("RASATHANE_SESSION_TOKEN"):
            return JSONResponse({"error": "Native uygulama oturumu gerekli."}, status_code=403)
        try:
            body = await _input(request, ServiceSession)
            set_service_session(body.get("access_token"))
            await run_in_threadpool(
                get_service().set_native_authenticated, body.get("access_token") is not None
            )
            return JSONResponse({"configured": body.get("access_token") is not None})
        except (ValidationError, ValueError):
            return JSONResponse({"error": "Hesap oturum girdisi geçersiz."}, status_code=422)

    @mcp.custom_route("/api/rasathane/{resource}", methods=["GET", "POST", "OPTIONS"])
    async def product_collection(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        resource = request.path_params["resource"]
        service = get_service()
        store = service.store
        try:
            if request.method == "GET":
                if resource == "state":
                    return JSONResponse(await run_in_threadpool(service.state))
                if resource == "articles":
                    filters = ArticleQuery.model_validate(dict(request.query_params))
                    return JSONResponse(
                        await run_in_threadpool(store.article_page, **filters.model_dump())
                    )
                lists = {
                    "jobs": lambda: store.list_jobs(brief=True),
                    "workspaces": store.list_workspaces,
                    "topics": store.list_topics,
                    "library": lambda: store.library(brief=True),
                    "sources": store.list_feeds,
                    "bulletins": store.list_bulletins,
                    "conversations": lambda: store.list_conversations(
                        request.query_params.get("workspace_id")
                    ),
                }
                if resource in lists:
                    return JSONResponse({"items": await run_in_threadpool(lists[resource])})
                if resource == "notes":
                    return JSONResponse(
                        {
                            "items": await run_in_threadpool(
                                store.list_notes, request.query_params.get("workspace_id")
                            )
                        }
                    )
                if resource == "settings":
                    return JSONResponse(await run_in_threadpool(store.settings))
                if resource == "export":
                    workspace_id = request.query_params.get("workspace_id")
                    if workspace_id is not None and len(workspace_id) > 64:
                        raise ValueError("Çalışma alanı kimliği geçersiz.")
                    snapshot = await run_in_threadpool(store.export, workspace_id)
                    return JSONResponse(
                        snapshot,
                        headers={
                            "Content-Disposition": 'attachment; filename="Rasathane-Export.json"'
                        },
                    )
                return JSONResponse({"error": "Uç bulunamadı."}, status_code=404)
            models: dict[str, type[Input]] = {
                "analysis": Analysis,
                "research": Research,
                "workspaces": Workspace,
                "notes": Note,
                "topics": Topic,
                "sources": Source,
                "settings": Settings,
                "bulletins": Bulletin,
            }
            if resource not in models:
                return JSONResponse({"error": "Uç bulunamadı."}, status_code=404)
            body = await _input(request, models[resource])
            if resource in {"analysis", "research"}:
                return JSONResponse(
                    await run_in_threadpool(service.submit, resource, body), status_code=202
                )
            if resource == "bulletins":
                from rasathane.product.bulletins import create_bulletin

                result = await run_in_threadpool(create_bulletin, store, **body)
            elif resource == "workspaces":
                result = await run_in_threadpool(store.create_workspace, body["name"].strip())
            elif resource == "notes":
                result = await run_in_threadpool(store.save_note, **body)
            elif resource == "topics":
                result = await run_in_threadpool(
                    store.create_topic, body["name"].strip(), body["query"].strip()
                )
            elif resource == "sources":
                body["url"] = validate_public_url(body["url"])
                result = await run_in_threadpool(store.upsert_feed, **body)
            else:
                result = await run_in_threadpool(store.save_settings, body)
            return JSONResponse(result, status_code=200 if resource == "settings" else 201)
        except ValidationError as exc:
            return JSONResponse(
                {
                    "error": "Girdi geçersiz.",
                    "fields": [
                        {"field": ".".join(map(str, row["loc"])), "type": row["type"]}
                        for row in exc.errors()
                    ],
                },
                status_code=422,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)[:300]}, status_code=400)
        except Exception:
            return JSONResponse(
                {"error": "Yerel işlem tamamlanamadı; uygulama loglarını kontrol edin."},
                status_code=500,
            )

    @mcp.custom_route("/api/rasathane/{resource}/{item_id}/{action}", methods=["POST", "OPTIONS"])
    async def product_action(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        resource, item_id, action = (
            request.path_params[key] for key in ("resource", "item_id", "action")
        )
        if len(item_id) > 64:
            return JSONResponse({"error": "Kimlik geçersiz."}, status_code=400)
        service = get_service()
        try:
            if resource == "sources" and action == "update":
                body = await _input(request, SourceUpdate)
                if "url" in body:
                    body["url"] = validate_public_url(body["url"])
                return JSONResponse(
                    await run_in_threadpool(service.store.update_feed, item_id, **body)
                )
            if resource == "bulletins" and action == "speech":
                from rasathane.product.bulletins import speak_bulletin

                audio = await run_in_threadpool(speak_bulletin, service.store, item_id)
                return Response(
                    audio, media_type="audio/wav", headers={"Cache-Control": "no-store"}
                )
            if resource == "articles" and action in {"summary", "speech"}:
                from rasathane.product.news import speak_article, summarize_article

                if action == "summary":
                    return JSONResponse(
                        await run_in_threadpool(summarize_article, service.store, item_id)
                    )
                audio = await run_in_threadpool(speak_article, service.store, item_id)
                return Response(
                    audio, media_type="audio/wav", headers={"Cache-Control": "no-store"}
                )
            if resource == "jobs" and action == "cancel":
                return JSONResponse(await run_in_threadpool(service.store.cancel, item_id))
            if resource == "topics" and action == "refresh":
                if not any(row["id"] == item_id for row in service.store.list_topics()):
                    raise ValueError("Konu takibi bulunamadı.")
                return JSONResponse(
                    await run_in_threadpool(service.submit, "refresh", {"topic_id": item_id}),
                    status_code=202,
                )
            if resource == "sources" and action == "refresh":
                if item_id != "all" and not any(
                    row["id"] == item_id for row in service.store.list_feeds()
                ):
                    raise ValueError("Kaynak bulunamadı.")
                return JSONResponse(
                    await run_in_threadpool(
                        service.submit,
                        "feed_refresh",
                        {"source_id": None if item_id == "all" else item_id},
                    ),
                    status_code=202,
                )
            return JSONResponse({"error": "Uç bulunamadı."}, status_code=404)
        except ValidationError:
            return JSONResponse({"error": "Kaynak bilgileri geçersiz."}, status_code=422)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)[:300]}, status_code=400)

    @mcp.custom_route("/api/rasathane/topics/{item_id}", methods=["GET", "OPTIONS"])
    async def product_topic(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        try:
            return JSONResponse(
                await run_in_threadpool(
                    get_service().store.get_topic, request.path_params["item_id"]
                )
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @mcp.custom_route("/api/rasathane/bulletins/{item_id}", methods=["GET", "OPTIONS"])
    async def product_bulletin(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        try:
            return JSONResponse(
                await run_in_threadpool(
                    get_service().store.get_bulletin, request.path_params["item_id"]
                )
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @mcp.custom_route("/api/rasathane/conversations/{item_id}", methods=["GET", "OPTIONS"])
    async def product_conversation(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        try:
            return JSONResponse(
                await run_in_threadpool(
                    get_service().store.get_conversation,
                    request.path_params["item_id"],
                    before=request.query_params.get("before"),
                    page_size=50,
                )
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @mcp.custom_route("/api/rasathane/jobs/{item_id}", methods=["GET", "OPTIONS"])
    async def product_job(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        try:
            return JSONResponse(
                await run_in_threadpool(get_service().store.get_job, request.path_params["item_id"])
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
