from __future__ import annotations

import asyncio
import html
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any, AsyncGenerator

import httpx

from backend.app.core.config import settings
from backend.app.services.llm import answer_budget, generate, generate_stream, language_instruction

log = logging.getLogger(__name__)


@dataclass
class ResearchSource:
    source: str
    title: str
    url: str
    snippet: str


TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=10.0)
USER_AGENT = "Lumina-Local-AI/6.0 research client"


def _clean(text: str, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    return text[:limit]


def _google_enabled() -> bool:
    return settings().google_search_configured


async def google_search(client: httpx.AsyncClient, query: str, limit: int) -> list[ResearchSource]:
    if not _google_enabled():
        return []
    params = {
        "key": settings().google_api_key,
        "cx": settings().google_cse_id,
        "q": query,
        "num": min(limit, 10),
        "safe": "active",
    }
    r = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
    r.raise_for_status()
    data = r.json()
    return [
        ResearchSource("Google", item.get("title", ""), item.get("link", ""), _clean(item.get("snippet", "")))
        for item in data.get("items", [])
        if item.get("link")
    ]


async def github_search(client: httpx.AsyncClient, query: str, limit: int) -> list[ResearchSource]:
    r = await client.get(
        "https://api.github.com/search/repositories",
        params={"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, 10)},
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    return [
        ResearchSource(
            "GitHub",
            item.get("full_name", ""),
            item.get("html_url", ""),
            _clean(item.get("description", "")),
        )
        for item in r.json().get("items", [])
        if item.get("html_url")
    ]


async def gitlab_search(client: httpx.AsyncClient, query: str, limit: int) -> list[ResearchSource]:
    r = await client.get(
        "https://gitlab.com/api/v4/projects",
        params={"search": query, "order_by": "star_count", "sort": "desc", "per_page": min(limit, 10)},
        headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    return [
        ResearchSource(
            "GitLab",
            item.get("path_with_namespace", ""),
            item.get("web_url", ""),
            _clean(item.get("description", "")),
        )
        for item in r.json()
        if item.get("web_url")
    ]


async def stackoverflow_search(client: httpx.AsyncClient, query: str, limit: int) -> list[ResearchSource]:
    r = await client.get(
        "https://api.stackexchange.com/2.3/search/advanced",
        params={"site": "stackoverflow", "q": query, "order": "desc", "sort": "relevance", "pagesize": min(limit, 10)},
    )
    r.raise_for_status()
    return [
        ResearchSource("Stack Overflow", _clean(item.get("title", "")), item.get("link", ""), _clean(item.get("title", "")))
        for item in r.json().get("items", [])
        if item.get("link")
    ]


async def arxiv_search(client: httpx.AsyncClient, query: str, limit: int) -> list[ResearchSource]:
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": min(limit, 10),
        "sortBy": "relevance",
    }
    r = await client.get("https://export.arxiv.org/api/query", params=params)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    results = []
    for entry in root.findall("a:entry", ns):
        title = _clean(entry.findtext("a:title", default="", namespaces=ns))
        summary = _clean(entry.findtext("a:summary", default="", namespaces=ns))
        link = ""
        for link_node in entry.findall("a:link", ns):
            if link_node.attrib.get("rel") == "alternate":
                link = link_node.attrib.get("href", "")
                break
        if link:
            results.append(ResearchSource("arXiv", title, link, summary))
    return results


async def huggingface_search(client: httpx.AsyncClient, query: str, limit: int) -> list[ResearchSource]:
    r = await client.get(
        "https://huggingface.co/api/models",
        params={"search": query, "limit": min(limit, 10), "sort": "downloads", "direction": -1},
        headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    return [
        ResearchSource(
            "Hugging Face",
            item.get("id", ""),
            f"https://huggingface.co/{item.get('id', '')}",
            f"Downloads: {item.get('downloads', 0)} | Likes: {item.get('likes', 0)}",
        )
        for item in r.json()
        if item.get("id")
    ]


async def duckduckgo_search(client: httpx.AsyncClient, query: str, limit: int) -> list[ResearchSource]:
    # Fallback when Google CSE credentials are not configured.
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
    r = await client.get(url, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    results = []
    pattern = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    for href, title_html in pattern.findall(r.text)[:limit]:
        title = re.sub(r"<.*?>", "", title_html)
        href = html.unescape(href)
        results.append(ResearchSource("Web", _clean(title), href, "Web search result"))
    return results


async def search_all(query: str, limit_per_source: int = 5) -> list[ResearchSource]:
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        jobs = [
            github_search(client, query, limit_per_source),
            gitlab_search(client, query, limit_per_source),
            stackoverflow_search(client, query, limit_per_source),
            arxiv_search(client, query, limit_per_source),
            huggingface_search(client, query, limit_per_source),
        ]
        if _google_enabled():
            jobs.append(google_search(client, query, limit_per_source))
        else:
            jobs.append(duckduckgo_search(client, query, limit_per_source))

        results = await asyncio.gather(*jobs, return_exceptions=True)

    sources: list[ResearchSource] = []
    seen: set[str] = set()
    for result in results:
        if isinstance(result, Exception):
            log.warning("Research source failed: %s", result)
            continue
        for source in result:
            key = source.url.lower().strip()
            if key and key not in seen:
                seen.add(key)
                sources.append(source)
    return sources


def build_research_prompt(
    question: str,
    sources: list[ResearchSource],
    document_context: str = "",
    budget_chars: int = 21000,
) -> str:
    evidence = "\n\n".join(
        f"SOURCE {i}: {s.source}\nTITLE: {s.title}\nURL: {s.url}\nINFO: {s.snippet}"
        for i, s in enumerate(sources, start=1)
    ) or "No external web results were returned."

    return f"""Answer the user's research question using the evidence below.

USER QUESTION:
{question}

DOCUMENT CONTEXT (if supplied):
{document_context[:int(budget_chars * 0.35)] or "None"}

EXTERNAL RESEARCH:
{evidence[:int(budget_chars * 0.65)]}

Instructions:
- Synthesize the evidence instead of merely listing links.
- Clearly distinguish document facts from external information.
- Cite sources inline as [Source N].
- Do not invent facts, citations, URLs, statistics, versions, or claims.
- If sources disagree or evidence is thin, say so.
- Use clean Markdown with short headings and bullet points.
"""


RESEARCH_SYSTEM = "You are a careful research assistant. Ground every claim in the supplied evidence."


def research_plan(model: str | None) -> dict:
    """How much evidence to read and how long to write on THIS computer."""
    return answer_budget(model, settings().research_max_tokens, extra_chars=900, max_context_chars=21000)


async def synthesize_research(
    question: str,
    sources: list[ResearchSource],
    document_context: str = "",
    model: str | None = None,
) -> str:
    plan = research_plan(model)
    return await generate(
        build_research_prompt(question, sources, document_context, plan["context_chars"]),
        system=RESEARCH_SYSTEM,
        temperature=0.1,
        max_tokens=plan["max_tokens"],
        model=model,
    )


async def stream_research(
    question: str,
    sources: list[ResearchSource],
    document_context: str = "",
    model: str | None = None,
    language: str | None = None,
) -> AsyncGenerator[str, None]:
    # Sized for this PC's speed so web answers also arrive within about a minute:
    # on a slow CPU less evidence is read and the answer is shorter.
    plan = research_plan(model)
    async for token in generate_stream(
        build_research_prompt(question, sources, document_context, plan["context_chars"]),
        system=RESEARCH_SYSTEM + " " + language_instruction(language),
        temperature=0.1,
        max_tokens=plan["max_tokens"],
        model=model,
    ):
        yield token


def platforms() -> list[str]:
    return [
        "Google Custom Search" if _google_enabled() else "DuckDuckGo",
        "GitHub", "GitLab", "Stack Overflow", "arXiv", "Hugging Face",
    ]


async def research_question(
    question: str,
    document_context: str = "",
    limit_per_source: int = 5,
    model: str | None = None,
) -> dict[str, Any]:
    sources = await search_all(question, limit_per_source=limit_per_source)
    answer = await synthesize_research(question, sources, document_context, model=model)
    return {
        "answer": answer,
        "sources": [asdict(source) for source in sources],
        "source_count": len(sources),
        "google_enabled": _google_enabled(),
        "search_platforms": platforms(),
    }
