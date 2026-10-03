"""Small, deterministic chat synthesis with verbatim, locally auditable evidence.

This path does not present model memory or search snippets as a legal conclusion.
Conversation context is used locally only; callers retain the original web query.
"""

from __future__ import annotations

import re
from math import ceil
from typing import Any

from rasathane.product.store import ProductStore, digest, fold

STOP_WORDS = frozenset(
    "ve veya ile icin hakkinda ne nedir neden nasil biliyoruz bana bir bu bunu bunlari "
    "bunlar bunun su o mi mu mıdır midir acikla anlat ozetle ayrintilandir detaylandir "
    "lutfen hangi olarak konusunda bilgi ver var nelerdir hangileridir nasil olur".split()
)
GENERAL_ACTION = re.compile(
    r"(?:yapil|gerceklestiril|uygulan|edil|veril|alin|ol)"
    r"(?:ir|ur|abilir|abilirler|mali|maktadir|acak|uyor|du|mus)$"
)
CHAT_RESULT_FIELDS = (
    "answer",
    "answer_kind",
    "answer_label",
    "citations",
    "errors",
    "status",
    "provider",
    "context_used",
    "query",
    "conversation_id",
    "turn_id",
)


def compact_chat_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = {key: result[key] for key in CHAT_RESULT_FIELDS if result.get(key) is not None}
    for key, limit in (
        ("answer", 6000),
        ("query", 500),
        ("answer_label", 100),
        ("status", 64),
        ("answer_kind", 64),
        ("provider", 100),
        ("conversation_id", 64),
        ("turn_id", 64),
    ):
        if key in compact:
            value = str(compact[key])
            compact[key] = value[:limit]
            if key == "answer" and len(value) > limit:
                compact["answer_truncated"] = True
    compact["errors"] = [str(error)[:300] for error in (result.get("errors") or [])[:3]]
    citations = []
    for source in (result.get("citations") or [])[:6]:
        citation = {}
        for key, limit in (
            ("title", 240),
            ("url", 2048),
            ("quote", 700),
            ("source_id", 128),
            ("version_id", 128),
            ("evidence_hash", 64),
            ("content_hash", 64),
            ("retrieved_at", 64),
            ("scope", 64),
        ):
            if source.get(key) is not None:
                citation[key] = str(source[key])[:limit]
        for key in ("number", "quote_start", "quote_end"):
            if isinstance(source.get(key), int):
                citation[key] = source[key]
        citations.append(citation)
    compact["citations"] = citations
    return compact


def query_terms(query: str) -> list[str]:
    return list(
        dict.fromkeys(
            word
            for word in re.findall(r"\w+", fold(query))
            if word not in STOP_WORDS and not GENERAL_ACTION.fullmatch(word)
        )
    )[:16]


def lexical_root(word: str) -> str:
    # Conservative plural/possessive suffix normalization; not semantic search or
    # a general Turkish stemmer. Keep at least four letters to avoid short roots.
    for suffix in (
        "larinin",
        "lerinin",
        "larina",
        "lerine",
        "larin",
        "lerin",
        "lari",
        "leri",
        "lar",
        "ler",
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def contextual_query(query: str) -> bool:
    return bool(
        re.search(
            r"\b(bunu|bunun|bunlar\w*|bu (karar|kaynak|sonuc|konu)\w*|"
            r"devam|ayrintilandir|detaylandir)\b",
            fold(query),
        )
    )


def local_results(
    store: ProductStore, query: str, workspace_id: str | None
) -> list[dict[str, Any]]:
    exact = store.search(query, workspace_id)
    if exact:
        return exact
    terms = query_terms(query)
    if not terms:
        return []
    reduced = store.search(" ".join(terms), workspace_id)
    if reduced:
        return reduced
    roots = list(dict.fromkeys(lexical_root(term) for term in terms))
    normalized = store.search(" ".join(roots), workspace_id)
    if normalized:
        return normalized
    # Bounded OR candidate collection with a coverage floor. Generic action words
    # do not pull unrelated documents into a "how" question. One shared word in
    # a long, unrelated query is insufficient evidence of relevance.
    candidates = {
        row["id"]: row for root in roots[:12] for row in store.search(root, workspace_id, limit=10)
    }
    ranked = []
    for row in candidates.values():
        tokens = re.findall(r"\w+", fold(row["title"] + " " + row["body"]))
        coverage = sum(any(token.startswith(root) for token in tokens) for root in roots)
        if coverage < ceil(len(roots) * 2 / 3):
            continue
        title_tokens = re.findall(r"\w+", fold(row["title"]))
        title_score = sum(any(token.startswith(root) for token in title_tokens) for root in roots)
        ranked.append((coverage, title_score, row))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]["score"]))
    return [item[2] for item in ranked[:20]]


def answer_from_sources(
    result: dict[str, Any],
    previous: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    terms = query_terms(result["query"])
    candidates = [*result["local_results"], *result["web_results"]]
    context_used = False
    if contextual_query(result["query"]) and previous:
        candidates.extend(previous)
        context_used = True
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        body = str(row.get("body") or row.get("quote") or row.get("excerpt") or "")
        if not body.strip():
            continue
        provenance = row.get("provenance") or {}
        source_id = row.get("source_id") or row.get("id") or row.get("url") or digest(body)
        key = str(source_id)
        if key in seen:
            continue
        # Every displayed quote is an exact slice; no paraphrase can silently alter
        # dates, amounts, negation, case references or statutory wording.
        spans = list(re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", body))
        ranked = sorted(spans, key=lambda span: -sum(term in fold(span.group()) for term in terms))
        selected = ranked[0] if ranked else None
        quote = selected.group().strip()[:700] if selected else body[:700]
        if not quote:
            continue
        inherited = bool(row.get("quote") and row.get("evidence_hash") and not row.get("body"))
        if inherited:
            # Prior evidence offsets/hash describe the original source body, not
            # the extracted quote. Reuse the whole quote and its receipt unchanged.
            quote = row["quote"]
        start = row["quote_start"] if inherited else body.find(quote)
        seen.add(key)
        citations.append(
            {
                "number": len(citations) + 1,
                "source_id": source_id,
                "version_id": row.get("version_id") or provenance.get("version_id"),
                "title": row.get("title") or "Yerel kaynak",
                "url": row.get("url"),
                "quote": quote,
                "quote_start": start,
                "quote_end": row["quote_end"] if inherited else start + len(quote),
                "evidence_hash": row["evidence_hash"] if inherited else digest(body),
                "content_hash": row.get("content_hash") or provenance.get("content_hash"),
                "retrieved_at": row.get("retrieved_at") or provenance.get("retrieved_at"),
                "scope": row.get("fetch_status") or row.get("scope") or row.get("kind") or "local",
            }
        )
        if len(citations) == 6:
            break
    if not citations:
        answer = (
            "Bu soruyu yanıtlamak için yeterli kaynak metni bulamadım. "
            "Konuyu karar numarası veya birkaç belirgin kelimeyle daraltabilir, "
            "çalışma alanına kaynak ekleyebilir ya da web aramasını açabilirsiniz."
        )
    else:
        intro = (
            "Önceki konuşmanın kaynaklarıyla birlikte bulduğum ilgili bölümler:"
            if context_used
            else "Sorunuzla ilgili kaynaklarda şu bölümleri buldum:"
        )
        answer = (
            intro
            + "\n\n"
            + "\n\n".join(
                f"[{item['number']}] {item['title']}\n“{item['quote']}”" for item in citations
            )
        )
        answer += (
            "\n\nBu yanıt kaynak alıntılarından derlendi. Alıntılar tek başına sorunun "
            "kesin yanıtını veya güncel hukuki durumu doğrulamaz. "
            "İsterseniz bir kaynağı belirterek soruyu daraltın."
        )
    return {
        "answer": answer,
        "answer_kind": "source_extracts" if citations else "no_sources",
        "answer_label": "Kaynak alıntılarıyla yanıt" if citations else "Kaynak bulunamadı",
        "citations": citations,
        "context_used": context_used,
    }
