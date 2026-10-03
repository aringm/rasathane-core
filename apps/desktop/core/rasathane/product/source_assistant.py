"""Local, bounded source configuration chat with durable action receipts.

Publisher content is used only for feed discovery, never as instructions. The
assistant cannot delete data, run code, or change settings outside feed records.
No external language model receives the user's messages or source catalogue.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from rasathane.product.connectors import _legacy_feed_url
from rasathane.product.source_catalog import RADAR_CATEGORIES
from rasathane.product.store import ProductStore, fold, json_text, now
from rasathane.product.web import safe_get, validate_public_url

_lock = threading.RLock()
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_DOMAIN = re.compile(r"(?<![\w@])(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+(?:/[^\s<>\"']*)?")
CATEGORY_LABELS = {
    "genel": "Genel",
    "resmi_mevzuat": "Resmî mevzuat",
    "turk_hukuku": "Türk hukuku",
    "dunya_ai": "Dünya AI",
    "turkiye_ai": "Türkiye AI",
    "legaltech": "Legaltech",
    "muhakeme_stack": "Geliştirme",
    "model_infra": "Model altyapısı",
    "open_weight_models": "Açık modeller",
    "china_ai_models": "Çin AI",
    "east_asia_ai_models": "Doğu Asya AI",
    "social_watch": "Sosyal medya",
}
_CATALOG = {
    "ai": [
        ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
        ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
        ("Simon Willison", "https://simonwillison.net/atom/everything"),
    ],
    "hukuk": [
        ("Lexpera Blog", "https://blog.lexpera.com.tr/feed"),
        ("Hukuki Haber", "https://hukukihaber.net/rss"),
        ("Artificial Lawyer", "https://artificiallawyer.com/feed"),
    ],
    "model": [
        ("llama.cpp", "https://github.com/ggml-org/llama.cpp/releases.atom"),
        ("Ollama", "https://github.com/ollama/ollama/releases.atom"),
        ("vLLM", "https://github.com/vllm-project/vllm/releases.atom"),
    ],
}


class Service(Protocol):
    store: ProductStore

    def _session_ready(self) -> bool: ...


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    request_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class Clarification(ValueError):
    pass


class _Discovery(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key.lower(): value or "" for key, value in attrs}
        if (
            tag == "link"
            and "alternate" in data.get("rel", "").lower().split()
            and data.get("type", "").lower().split(";")[0].strip()
            in {"application/rss+xml", "application/atom+xml"}
            and data.get("href")
        ):
            self.links.append(data["href"])


def _category(value: str) -> str:
    value = value.strip(" \t\r\n\"'’“”.,:;")
    if not value or len(value) > 80:
        raise Clarification("Kategori adı 1–80 karakter olmalı.")
    aliases = {fold(label): key for key, label in CATEGORY_LABELS.items()}
    aliases.update({fold(key): key for key in CATEGORY_LABELS})
    aliases.update({"hukuk": "turk_hukuku", "ai": "dunya_ai", "yapay zeka": "dunya_ai"})
    return aliases.get(fold(value), value)


def _category_in(message: str) -> str | None:
    # Quoted names allow arbitrary multiword project categories without guessing.
    quoted = re.search(r'["“]([^"”]{1,80})["”]\s*kategoris(?:ine|inde|i)', message, re.I)
    if quoted:
        return _category(quoted.group(1))
    normalized = fold(message)
    for label in sorted(
        [*CATEGORY_LABELS.values(), *CATEGORY_LABELS, "yapay zeka", "hukuk", "AI"],
        key=len,
        reverse=True,
    ):
        if re.search(
            r"(?<!\w)" + re.escape(fold(label)) + r"\s+kategoris(?:ine|inde|i)", normalized
        ):
            return _category(label)
    match = re.search(r"([^\s]+)\s+kategoris(?:ine|inde|i)", message, re.I)
    if match:
        return _category(match.group(1))
    return None


def _url_in(message: str) -> str | None:
    urls = _URL.findall(message)
    if not urls:
        urls = ["https://" + item for item in _DOMAIN.findall(message)]
    if len(urls) > 1:
        raise Clarification(
            "Her mesajda tek kaynak adresi gönderin; kaynakları ayrı ayrı doğrulayalım."
        )
    return urls[0].rstrip(".,;:!?)’") if urls else None


def _feed_title(content: bytes) -> str | None:
    if len(content) > 2_000_000:
        raise ValueError("Kaynak keşif yanıtı 2 MB sınırını aşıyor; doğrudan RSS adresini yazın.")
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        # HTML commonly has a doctype, but no XML entity expansion is allowed.
        if b"<!ENTITY" in content.upper() or b"<!DOCTYPE RSS" in content.upper():
            raise ValueError("RSS içinde DTD veya entity tanımları desteklenmez.")
        return None
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    if root.tag == "rss" and root.find("channel") is not None:
        return root.findtext("channel/title") or "RSS kaynağı"
    if root.tag == "{http://www.w3.org/2005/Atom}feed":
        return root.findtext("{http://www.w3.org/2005/Atom}title") or "Atom kaynağı"
    return None


def discover_source(url: str) -> dict[str, str]:
    """Fetch at most a page and its sole advertised feed; never guess /feed URLs."""
    target = validate_public_url(url)
    host = urlsplit(target).hostname or ""
    kind = "rss"
    if host in {"youtube.com", "www.youtube.com"}:
        kind = "youtube_channel"
        target = _legacy_feed_url({"url": target, "kind": kind})
    elif host in {"reddit.com", "www.reddit.com", "old.reddit.com"}:
        kind = "reddit"
        target = _legacy_feed_url({"url": target, "kind": kind})
    elif host in {"arxiv.org", "export.arxiv.org", "rss.arxiv.org"}:
        kind = "arxiv"
        parts = urlsplit(target)
        if parts.path.startswith("/list/"):
            topic = parts.path.split("/")[2]
            if not re.fullmatch(r"[a-zA-Z0-9.-]+", topic):
                raise Clarification("Geçerli bir arXiv konu RSS adresi gönderin.")
            target = "https://rss.arxiv.org/rss/" + topic
        else:
            target = _legacy_feed_url({"url": target, "kind": kind})
    content = safe_get(target)
    title = _feed_title(content)
    if title is None:
        discovery = _Discovery()
        discovery.feed(content.decode("utf-8", errors="replace"))
        links = list(
            dict.fromkeys(validate_public_url(urljoin(target, link)) for link in discovery.links)
        )
        if len(links) > 1:
            raise Clarification(
                "Bu sitede birden fazla RSS akışı var. Eklemek istediğiniz RSS adresini gönderin: "
                + " · ".join(links[:3])
            )
        if not links:
            raise Clarification(
                "Bu adreste doğrulanabilir RSS/Atom akışı bulunamadı. Sitenin RSS adresini "
                "veya YouTube kanal / Reddit topluluk adresini gönderin."
            )
        target = links[0]
        title = _feed_title(safe_get(target))
        if title is None:
            raise Clarification(
                "Sitenin duyurduğu bağlantı geçerli bir RSS/Atom akışı döndürmedi. "
                "Başka bir RSS adresi gönderin."
            )
    title = " ".join((title or host).split())[:120]
    return {"name": title, "url": target, "kind": kind}


def _init(store: ProductStore) -> None:
    with store.connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS source_assistant_turns "
            "(id TEXT PRIMARY KEY,message TEXT NOT NULL,result TEXT NOT NULL,"
            "created_at TEXT NOT NULL)"
        )


def history(store: ProductStore) -> dict[str, Any]:
    _init(store)
    with store.connection() as conn:
        rows = conn.execute(
            "SELECT result FROM source_assistant_turns ORDER BY rowid DESC LIMIT 100"
        ).fetchall()
    return {"items": [json.loads(row[0]) for row in reversed(rows)]}


def _snapshot(feed: dict[str, Any]) -> dict[str, Any]:
    return {key: feed.get(key) for key in ("id", "name", "url", "kind", "category", "enabled")}


def _match_source(store: ProductStore, message: str, url: str | None) -> dict[str, Any]:
    feeds = store.list_feeds()
    if url:
        target = validate_public_url(url)
        matches = [row for row in feeds if row["url"].rstrip("/") == target.rstrip("/")]
        if not matches and not _URL.search(message):
            # Product names such as llama.cpp look like bare domains. An exact
            # saved name is still a valid target when no explicit URL was given.
            normalized = fold(message)
            matches = [
                row
                for row in feeds
                if re.search(r"(?<!\w)" + re.escape(fold(row["name"])) + r"(?!\w)", normalized)
            ]
    else:
        normalized = fold(message)
        matches = [
            row
            for row in feeds
            if re.search(r"(?<!\w)" + re.escape(fold(row["name"])) + r"(?!\w)", normalized)
        ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise Clarification(
            "Hangi kaynağı değiştireyim? Kaynaklar listesindeki tam adını "
            "veya kayıtlı adresini yazın."
        )
    raise Clarification(
        "Birden fazla kaynak eşleşti: "
        + ", ".join(row["name"] for row in matches[:5])
        + ". Tek kaynağın kayıtlı adresini gönderin."
    )


def _suggestions(message: str) -> list[dict[str, str]]:
    normalized = fold(message)
    group = (
        "hukuk"
        if "hukuk" in normalized or "legal" in normalized
        else "model"
        if "model" in normalized
        else "ai"
    )
    return [
        {
            "name": name,
            "url": url,
            "category": RADAR_CATEGORIES[url],
            "prompt": f"{url} adresini {CATEGORY_LABELS[RADAR_CATEGORIES[url]]} kategorisine ekle",
        }
        for name, url in _CATALOG[group]
    ]


def _execute(store: ProductStore, message: str, guard: Callable[[], bool]) -> dict[str, Any]:
    # An address is data: path words such as /ac/ or /duraklat/ cannot issue
    # instructions. Category names may contain the same verbs as commands.
    command = _DOMAIN.sub("", _URL.sub("", message))
    command = re.sub(r'["“][^"”]{1,80}["”](?=\s*kategoris)', "", command, flags=re.I)
    normalized = fold(command)
    if re.search(
        r"\b(sil|silme|kaldir|kaldirma|format|sql|shell|powershell|token|parola)\b", normalized
    ):
        raise Clarification(
            "Bu sohbet yalnız kaynak ekleme, kategorilendirme ve takibi duraklatma/açma "
            "işlemlerini yapar. Silmek yerine kaynağın tam adıyla ‘duraklat’ yazabilirsiniz."
        )
    if re.search(
        r"\b(ekleme|tasima|duraklatma|acma|iptal|vazgec|degistirme|"
        r"istemiyorum|isteme|yapma|hayir|degil)\b",
        normalized,
    ):
        raise Clarification(
            "Değişiklik yapılmadı. Uygulanmasını istediğiniz işlemi "
            "tek bir kaynak için açıkça yazın."
        )
    url = _url_in(message)
    category = _category_in(message)
    pause = bool(re.search(r"\b(duraklat|durdur|kapat)\b", normalized))
    resume = bool(re.search(r"\b(etkinlestir|baslat|ac)\b|takibe al|devam et", normalized))
    move = bool(re.search(r"\b(tasi|degistir|kategorilendir)\b", normalized))
    if sum((pause, resume, move)) > 1:
        raise Clarification(
            "Her mesajda tek değişiklik yapalım: takibi duraklat/aç veya kategoriyi değiştir."
        )
    if pause or resume or move:
        feed = _match_source(store, message, url)
        if move and not category:
            raise Clarification(
                'Hedef kategoriyi yazın. Örnek: Lexpera kaynağını "İş hukuku" kategorisine taşı.'
            )
        if not guard():
            raise PermissionError("İşlem için yeniden giriş yapın.")
        before = _snapshot(feed)
        updated = (
            store.update_feed(feed["id"], category=category)
            if move
            else store.update_feed(feed["id"], enabled=resume)
        )
        text = (
            f"{feed['name']} → {CATEGORY_LABELS.get(category or '', category)} "
            "kategorisine taşındı."
            if move
            else f"{feed['name']} için kaynak takibi {'açıldı' if resume else 'duraklatıldı'}."
        )
        return {
            "status": "applied",
            "reply": text + " Mevcut haberler korundu.",
            "actions": [{"operation": "update", "before": before, "source": _snapshot(updated)}],
        }
    if url:
        command_text = fold(_DOMAIN.sub("", _URL.sub("", message))).strip(" .,;!\"'’“”")
        if re.search(
            r"\b(nedir|incele|ozetle|analiz|guvenilir|oner)\b|\?",
            command_text,
        ):
            raise Clarification(
                "Bu sohbet kaynak yapılandırır. Eklemek için ‘adres + ekle’, "
                "haber araştırmak için Araştır ekranını kullanın."
            )
        if command_text and not re.search(r"\bekle(?:r|yebilir)?\b|takip et", command_text):
            raise Clarification(
                "Bu adresi takip listesine eklememi istiyorsanız ‘adresi ekle’ yazın "
                "veya yalnızca site/RSS adresini gönderin. Henüz değişiklik yapılmadı."
            )
        # Repeated add is a no-op: it must not rename or reactivate paused feeds.
        target = validate_public_url(url)
        existing = next(
            (row for row in store.list_feeds() if row["url"].rstrip("/") == target.rstrip("/")),
            None,
        )
        if existing:
            return {
                "status": "applied",
                "reply": f"{existing['name']} zaten kayıtlı. "
                "Kategori ve takip durumu değiştirilmedi.",
                "actions": [{"operation": "unchanged", "source": _snapshot(existing)}],
            }
        discovered = discover_source(url)
        existing = next(
            (
                row
                for row in store.list_feeds()
                if row["url"].rstrip("/") == discovered["url"].rstrip("/")
            ),
            None,
        )
        if existing:
            return {
                "status": "applied",
                "reply": f"Bu site {existing['name']} olarak zaten takip listesinde. "
                "Kategori ve takip durumu değiştirilmedi.",
                "actions": [{"operation": "unchanged", "source": _snapshot(existing)}],
            }
        if not guard():
            raise PermissionError("İşlem için yeniden giriş yapın.")
        chosen = category or RADAR_CATEGORIES.get(discovered["url"].rstrip("/"), "genel")
        feed = store.upsert_feed(
            discovered["name"], discovered["url"], discovered["kind"], category=chosen, enabled=True
        )
        return {
            "status": "applied",
            "reply": f"{feed['name']}, {CATEGORY_LABELS.get(chosen, chosen)} kategorisine eklendi. "
            "Otomatik kaynak takibi açık; ilk güncelleme arka planda yapılacak.",
            "actions": [{"operation": "add", "source": _snapshot(feed)}],
        }
    if any(
        term in normalized for term in ("oner", "kaynak", "yapay zeka", "hukuk", "ai ", "model")
    ):
        return {
            "status": "suggestions",
            "reply": "Özgün Radar kataloğundan kaynak önerileri aşağıda. "
            "İstediğiniz kaynağı seçin; "
            "RSS adresini doğrulayıp ekleyeceğim. Öneri listesi takip ayarlarınızı değiştirmedi.",
            "suggestions": _suggestions(message),
        }
    raise Clarification(
        "Bir site adresi gönderin; RSS akışını bulup ekleyeyim. Örnekler: “AI kaynakları öner”, "
        "“Lexpera kaynağını duraklat”, “Lexpera kaynağını Türk hukuku kategorisine taşı”. "
        "Çok kelimeli özel kategorileri çift tırnakla yazabilirsiniz."
    )


def respond(
    store: ProductStore,
    message: str,
    request_id: str | None = None,
    *,
    guard: Callable[[], bool] = lambda: True,
) -> dict[str, Any]:
    data = ChatInput(message=message, request_id=request_id)
    message = data.message.strip()
    if not message:
        raise ValueError("Mesaj boş olamaz.")
    with _lock:
        if not guard():
            raise PermissionError("İşlem için yeniden giriş yapın.")
        _init(store)
        item_id = data.request_id or uuid.uuid4().hex
        with store.connection() as conn:
            previous = conn.execute(
                "SELECT message,result FROM source_assistant_turns WHERE id=?", (item_id,)
            ).fetchone()
        if previous:
            if previous["message"] != message:
                raise ValueError("İstek kimliği başka bir mesaj için kullanılmış.")
            return dict(json.loads(previous["result"]))
        try:
            result = _execute(store, message, guard)
        except Clarification as exc:
            result = {"status": "clarification", "reply": str(exc)}
        except PermissionError:
            raise
        except (ValueError, OSError, httpx.HTTPError) as exc:
            result = {"status": "error", "reply": "Kaynak yapılandırılamadı: " + str(exc)[:300]}
        if not guard():
            raise PermissionError("İşlem için yeniden giriş yapın.")
        turn = {
            "id": item_id,
            "message": message,
            "reply": result["reply"],
            "status": result["status"],
            "actions": result.get("actions", []),
            "suggestions": result.get("suggestions", []),
            "created_at": now(),
        }
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO source_assistant_turns VALUES(?,?,?,?)",
                (item_id, message, json_text(turn), turn["created_at"]),
            )
        return turn


def register_routes(mcp: FastMCP, get_service: Callable[[], Service]) -> None:
    """Register before the generic /api/rasathane/{resource} collection route."""

    @mcp.custom_route("/api/rasathane/source-assistant/history", methods=["GET", "OPTIONS"])
    async def source_history(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        service = get_service()
        if not service._session_ready():
            return JSONResponse({"error": "Önce hesabınıza giriş yapın."}, status_code=401)
        return JSONResponse(await run_in_threadpool(history, service.store))

    @mcp.custom_route("/api/rasathane/source-assistant", methods=["POST", "OPTIONS"])
    async def source_message(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204)
        service = get_service()
        if not service._session_ready():
            return JSONResponse({"error": "Önce hesabınıza giriş yapın."}, status_code=401)
        try:
            if not request.headers.get("content-type", "").lower().startswith("application/json"):
                raise ValueError("JSON Content-Type zorunlu.")
            raw = await request.body()
            if len(raw) > 16_000:
                raise ValueError("Mesaj izin verilen boyutu aşıyor.")
            body = ChatInput.model_validate_json(raw)
            result = await run_in_threadpool(
                respond, service.store, body.message, body.request_id, guard=service._session_ready
            )
            return JSONResponse(result)
        except ValidationError:
            return JSONResponse({"error": "Mesaj veya istek kimliği geçersiz."}, status_code=422)
        except PermissionError:
            return JSONResponse({"error": "İşlem için yeniden giriş yapın."}, status_code=401)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)[:300]}, status_code=400)
        except Exception:
            return JSONResponse(
                {"error": "Kaynak asistanı yanıt veremedi; yeniden deneyin."}, status_code=500
            )
