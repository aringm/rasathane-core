"""Isolated integration QA only; synthetic data, real product routes, no user database."""

import json
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastmcp import FastMCP
from rasathane.product import api
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

root = Path(__file__).resolve().parents[4]
run = Path(sys.argv[1])
store = ProductStore(run / "data")
news_feed = store.upsert_feed("Hukuk Gündemi QA", "https://example.org/rss", enabled=False, category="turk_hukuku")
store.mark_feed(news_feed["id"])
store.add_articles(
    news_feed["id"],
    [
        {
            "id": "synthetic-news",
            "url": "https://example.org/haber",
            "title": "Sentetik QA haberi",
            "summary": (
                "Yeni düzenleme yayımlandı. Başvuru süresi otuz gündür. "
                "Başvurular çevrimiçi olarak yapılabilir."
            ),
        }
    ],
)
store.add_articles(
    news_feed["id"],
    [
        {
            "id": "synthetic-metadata",
            "url": "https://example.org/metadata",
            "title": "Sentetik karar künyesi",
            "summary": "Daire: 1, karar: 4",
            "published_at": "2000-01-01T00:00:00Z",
            "provenance": {"text_scope": "official_metadata"},
        }
    ],
)
space = store.create_workspace("Sentetik QA çalışma alanı")
store.save_note(
    space["id"],
    "Başvuru süresi",
    "Başvuru süresi otuz gündür. Başvurular çevrimiçi olarak yapılabilir.",
)
service = ProductService(store, autostart=False)
api._service = service
# Persist a real source-bound agenda in the isolated fixture. No publisher
# request or model download is made; the enabled source was checked above.
store.save_agenda_profile({
    "enabled": False, "use_local_model": False, "include_topics": False,
    "interests": "Başvuru süresi ve Türk hukuku",
    "project_context": "Başvuru iş akışındaki sürelerin incelenmesi",
    "workspace_ids": [space["id"]],
})
store.update_feed(news_feed["id"], enabled=True)
agenda_job = service.submit("agenda", {})
service.run_once()
assert store.get_job(agenda_job["id"])["status"] == "completed"
store.update_feed(news_feed["id"], enabled=False)
archive_id = None
for index in range(1, 56):
    archive_job = store.enqueue(
        "research",
        {
            "query": f"Uzun QA geçmişi · tur {index:02d}",
            "workspace_id": space["id"],
            "web": False,
            **({"conversation_id": archive_id} if archive_id else {}),
        },
    )
    archive_id = archive_job["request"]["conversation_id"]
    store.update_job(archive_job["id"], "completed", result={"answer": f"Arşiv yanıtı {index:02d}"})

if "--seed-only" in sys.argv[2:]:
    # Frozen acceptance uses the real scheduler, while fixture records remain local.
    # Disable web through the normal persisted product setting, not a runtime bypass.
    store.save_settings({"web_enabled": False})
    for feed in store.list_feeds():
        store.update_feed(feed["id"], enabled=False)
    (run / "seed.json").write_text(json.dumps({"workspace": space["id"]}))
    sys.exit(0)


def worker():
    while True:
        service.run_once()
        time.sleep(0.1)


threading.Thread(target=worker, daemon=True).start()
mcp = FastMCP("Isolated product QA")
api.register_routes(mcp)


@mcp.custom_route("/gui/{resource}", methods=["GET"])
async def gui(request):
    return JSONResponse(
        {
            "ok": True,
            "ner_erisilebilir": True,
            "tam_ozellik_hazir": True,
            "checks": [],
            "hazir": True,
            "items": [],
        }
    )


application = mcp.http_app()
application.router.routes.append(
    Mount("/", app=StaticFiles(directory=root / "apps/desktop/gui/ui", html=True))
)
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
(run / "server.json").write_text(json.dumps({"port": port, "workspace": space["id"]}))
uvicorn.Server(uvicorn.Config(application, log_level="error")).run(sockets=[sock])
