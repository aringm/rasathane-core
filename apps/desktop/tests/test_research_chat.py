from __future__ import annotations

import httpx
import pytest
from rasathane.product import api
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore
from ytmcp.server import gui_http_app


def test_conversation_survives_restart_with_bound_quotes_and_followup(tmp_path):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Araştırma")
    note = store.save_note(
        workspace["id"],
        "Kıdem tazminatı",
        "Kıdem tazminatı araştırması. Kaynak tarihini kontrol edin.",
    )
    service = ProductService(store, autostart=False)
    first = service.submit(
        "research",
        {
            "query": "Kıdem tazminatı hakkında ne biliyoruz?",
            "workspace_id": workspace["id"],
            "web": False,
        },
    )
    service.run_once()
    result = store.get_job(first["id"])["result"]
    assert result["answer_kind"] == "source_extracts"
    assert result["citations"][0]["source_id"] == note["id"]
    assert result["citations"][0]["quote"] in note["body"]
    followup = service.submit(
        "research",
        {
            "query": "Bunu ayrıntılandır",
            "conversation_id": first["request"]["conversation_id"],
            "web": False,
        },
    )
    service.run_once()
    assert store.get_job(followup["id"])["result"]["context_used"] is True
    reopened = ProductStore(tmp_path)
    chat = reopened.get_conversation(first["request"]["conversation_id"])
    assert len(chat["messages"]) == 4
    assert chat["workspace_id"] == workspace["id"]
    assert chat["messages"][-1]["status"] == "completed"
    assert reopened.export(workspace["id"])["conversations"][0]["messages"] == chat["messages"]


def test_no_answer_does_not_recycle_previous_unrelated_sources(tmp_path):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Araştırma")
    store.save_note(workspace["id"], "Kira", "Kira sözleşmesi koşulları")
    service = ProductService(store, autostart=False)
    first = service.submit(
        "research", {"query": "Kira", "workspace_id": workspace["id"], "web": False}
    )
    service.run_once()
    second = service.submit(
        "research",
        {
            "query": "Veraset ilamı uzay aracı",
            "conversation_id": first["request"]["conversation_id"],
            "web": False,
        },
    )
    service.run_once()
    result = store.get_job(second["id"])["result"]
    assert result["answer_kind"] == "no_sources"
    assert not result["citations"]


def test_only_current_query_leaves_computer_and_workspace_cannot_change(tmp_path):
    calls = []

    class Search:
        name = "fixture"

        def search(self, query, limit=5):
            calls.append(query)
            return []

    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Özel çalışma")
    service = ProductService(store, search=Search(), autostart=False)
    first = service.submit(
        "research", {"query": "Yerel özel not", "workspace_id": workspace["id"], "web": False}
    )
    service.run_once()
    second = service.submit(
        "research",
        {
            "query": "Bunu açıkla",
            "conversation_id": first["request"]["conversation_id"],
            "web": True,
        },
    )
    service.run_once()
    assert calls == ["Bunu açıkla"]
    assert store.get_job(second["id"])["status"] == "completed"
    other = store.create_workspace("Diğer")
    with pytest.raises(ValueError, match="çalışma alanı"):
        service.submit(
            "research",
            {
                "query": "q",
                "workspace_id": other["id"],
                "conversation_id": first["request"]["conversation_id"],
            },
        )


def test_pending_turn_rejected_cancel_reopens_conversation(tmp_path):
    store = ProductStore(tmp_path)
    service = ProductService(store, autostart=False)
    first = service.submit("research", {"query": "q", "web": False})
    cid = first["request"]["conversation_id"]
    with pytest.raises(ValueError, match="bekleyin"):
        service.submit("research", {"query": "again", "conversation_id": cid})
    store.cancel(first["id"])
    assert store.get_conversation(cid)["messages"][-1]["status"] == "cancelled"
    service.submit("research", {"query": "again", "conversation_id": cid, "web": False})


async def test_chat_api_lists_history_and_logout_cancels_pending_turn(tmp_path, monkeypatch):
    service = ProductService(ProductStore(tmp_path), autostart=False)
    monkeypatch.setattr(api, "_service", service)
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        first = await client.post("/api/rasathane/research", json={"query": "Kıdem", "web": False})
        assert first.status_code == 202
        cid = first.json()["request"]["conversation_id"]
        assert (await client.get("/api/rasathane/conversations")).json()["items"][0]["id"] == cid
        assert (await client.get("/api/rasathane/conversations/" + cid)).json()["messages"][0][
            "content"
        ] == "Kıdem"
        monkeypatch.setenv("RASATHANE_SESSION_TOKEN", "synthetic-session")
        logout = await client.post(
            "/api/product/service-session",
            json={"access_token": None},
            headers={"X-Rasathane-Session": "synthetic-session"},
        )
        assert logout.status_code == 200
        assert service.store.get_conversation(cid)["messages"][-1]["status"] == "cancelled"


def test_failed_and_interrupted_turns_remain_visible(tmp_path):
    class Broken:
        name = "fixture"

        def search(self, query, limit=5):
            raise RuntimeError("Sağlayıcı yanıt vermedi")

    store = ProductStore(tmp_path)
    service = ProductService(store, search=Broken(), autostart=False)
    job = service.submit("research", {"query": "Kıdem", "web": True})
    service.run_once()
    cid = job["request"]["conversation_id"]
    assert store.get_conversation(cid)["messages"][-1]["status"] == "failed"
    next_job = service.submit(
        "research", {"query": "Yeniden", "conversation_id": cid, "web": False}
    )
    store.claim_next()
    store.recover_interrupted()
    message = store.get_conversation(cid)["messages"][-1]
    assert message["status"] == "interrupted"
    assert message["job_id"] == next_job["id"]


def test_full_web_text_is_quoted_with_evidence_offsets(tmp_path):
    class Search:
        name = "fixture"

        def search(self, query, limit=5):
            return [
                {"title": "Kaynak", "url": "https://example.org/karar", "excerpt": "Eski alıntı"}
            ]

    body = "Başlangıç. Kıdem tazminatı 2026/42 sayılı dosyada incelendi. Başka bölüm."
    store = ProductStore(tmp_path)
    service = ProductService(
        store, search=Search(), fetch=lambda url: {"body": body}, autostart=False
    )
    job = service.submit("research", {"query": "Kıdem tazminatı", "web": True})
    service.run_once()
    result = store.get_job(job["id"])["result"]
    citation = result["citations"][0]
    assert citation["quote"] == body[citation["quote_start"] : citation["quote_end"]]
    assert "2026/42" in citation["quote"]
    assert "Eski alıntı" not in result["answer"]


def test_native_worker_and_scheduler_wait_for_authenticated_main(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("RASATHANE_SESSION_TOKEN", "synthetic-session")
    store = ProductStore(tmp_path)
    service = ProductService(store, autostart=False)
    topic = store.create_topic("İşçilik", "işçilik")
    with store.connection() as conn:
        conn.execute(
            "UPDATE topics SET last_refreshed_at=? WHERE id=?",
            (
                (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                topic["id"],
            ),
        )
    service._schedule()
    assert store.list_jobs() == []
    job = service.submit("research", {"query": "Kıdem", "web": False})
    assert service.run_once() is False
    service.set_native_authenticated(True)
    assert service.run_once() is True
    assert store.get_job(job["id"])["status"] == "completed"
    service._schedule()
    assert any(row["status"] == "queued" for row in store.list_jobs())
    service.set_native_authenticated(False)
    service._schedule()
    assert not any(row["status"] == "queued" for row in store.list_jobs())


def test_natural_followup_retrieves_inflected_source_and_rejects_distractors(tmp_path):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Başvurular")
    store.save_note(
        workspace["id"],
        "Başvuru süresi",
        "Başvuru süresi otuz gündür. Başvurular çevrimiçi olarak yapılabilir.",
    )
    store.save_note(workspace["id"], "Ödemeler", "Ödemeler banka üzerinden yapılır.")
    service = ProductService(store, autostart=False)
    first = service.submit(
        "research",
        {"query": "Başvuru süresi nedir?", "workspace_id": workspace["id"], "web": False},
    )
    service.run_once()
    cid = first["request"]["conversation_id"]
    followup = service.submit(
        "research", {"query": "Başvurular nasıl yapılır?", "conversation_id": cid, "web": False}
    )
    service.run_once()
    result = store.get_job(followup["id"])["result"]
    assert result["answer_kind"] == "source_extracts"
    assert result["citations"][0]["quote"] == "Başvurular çevrimiçi olarak yapılabilir."
    assert not any(row["title"] == "Ödemeler" for row in result["citations"])
    unrelated = service.submit(
        "research",
        {"query": "Başvurular uzay aracı veraset ilamı", "conversation_id": cid, "web": False},
    )
    service.run_once()
    assert store.get_job(unrelated["id"])["result"]["answer_kind"] == "no_sources"


@pytest.mark.parametrize(
    "query", ["Ödemeler nasıl gerçekleştirilir?", "Ödemelerin yöntemleri nelerdir?"]
)
def test_general_natural_query_patterns_are_not_fixture_specific(tmp_path, query):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Yöntemler")
    store.save_note(
        workspace["id"], "Ödeme yöntemleri", "Ödemeler banka üzerinden gerçekleştirilebilir."
    )
    service = ProductService(store, autostart=False)
    job = service.submit(
        "research", {"query": query, "workspace_id": workspace["id"], "web": False}
    )
    service.run_once()
    assert store.get_job(job["id"])["result"]["answer_kind"] == "source_extracts"


async def test_chat_history_paginates_compactly_without_discarding_export_evidence(
    tmp_path, monkeypatch
):
    import json

    store = ProductStore(tmp_path)
    service = ProductService(store, autostart=False)
    monkeypatch.setattr(api, "_service", service)
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN", raising=False)
    cid = None
    source_body = "Tam kaynak metni " * 6500
    result = {
        "answer": "Kaynak alıntısı",
        "answer_kind": "source_extracts",
        "citations": [],
        "local_results": [{"body": source_body}],
        "web_results": [{"body": source_body}],
    }
    for index in range(55):
        job = service.submit(
            "research", {"query": f"Soru {index}", "conversation_id": cid, "web": False}
        )
        cid = job["request"]["conversation_id"]
        store.update_job(job["id"], "completed", result=result)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        recent = await client.get("/api/rasathane/conversations/" + cid)
        assert recent.status_code == 200 and len(recent.content) < 200_000
        page = recent.json()
        assert len(page["messages"]) == 100
        assert page["messages"][0]["content"] == "Soru 5"
        assert page["messages"][-2]["content"] == "Soru 54"
        assert "local_results" not in page["messages"][1]["result"]
        previous = (
            await client.get(
                "/api/rasathane/conversations/" + cid, params={"before": page["next_before"]}
            )
        ).json()
        assert len(previous["messages"]) == 10 and previous["next_before"] is None
        questions = [
            message["content"]
            for message in previous["messages"] + page["messages"]
            if message["role"] == "user"
        ]
        assert questions == [f"Soru {index}" for index in range(55)]
        invalid = await client.get(
            "/api/rasathane/conversations/" + cid, params={"before": "unknown"}
        )
        assert invalid.status_code == 404
    exported = store.export()["conversations"][0]
    assert len(json.dumps(exported)) > 8 * 1024 * 1024
    assert len(exported["messages"]) == 110
    assert exported["messages"][1]["result"]["web_results"][0]["body"] == source_body


def test_followup_preserves_original_evidence_offsets_and_hash(tmp_path):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Kanıt")
    body = "Önce genel açıklama. Başvurular çevrimiçi olarak yapılabilir. Sonraki açıklama."
    store.save_note(workspace["id"], "Başvurular", body)
    service = ProductService(store, autostart=False)
    first = service.submit(
        "research",
        {"query": "Başvurular nasıl yapılır?", "workspace_id": workspace["id"], "web": False},
    )
    service.run_once()
    original = store.get_job(first["id"])["result"]["citations"][0]
    assert original["quote_start"] > 0
    followup = service.submit(
        "research",
        {
            "query": "Bunu ayrıntılandır",
            "conversation_id": first["request"]["conversation_id"],
            "web": False,
        },
    )
    service.run_once()
    inherited = store.get_job(followup["id"])["result"]["citations"][0]
    for key in ("quote", "quote_start", "quote_end", "evidence_hash", "content_hash", "source_id"):
        assert inherited[key] == original[key]
    assert inherited["quote"] == body[inherited["quote_start"] : inherited["quote_end"]]
