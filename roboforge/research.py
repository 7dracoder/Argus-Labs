"""Reference research: real robots that do the brief's job, with photos (Tavily web search).

The text model can't see pixels, so each photo comes with Tavily's written description;
both those and the page snippets go into the concept prompt. Any failure returns no
references and the concept is designed from the brief alone.
"""
from __future__ import annotations

import os

import httpx
from pydantic import BaseModel

TAVILY_URL = "https://api.tavily.com/search"


class Reference(BaseModel):
    title: str
    url: str
    snippet: str = ""


class ReferenceImage(BaseModel):
    url: str
    description: str = ""


class Research(BaseModel):
    references: list[Reference] = []
    images: list[ReferenceImage] = []


def find_references(brief: str) -> Research:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key or not brief.strip():
        return Research()
    query = f"real robot product or research prototype that can: {brief[:300]}"
    try:
        response = httpx.post(TAVILY_URL, timeout=20, headers={"Authorization": f"Bearer {key}"},
                              json={"query": query, "max_results": 5, "include_images": True,
                                    "include_image_descriptions": True})
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return Research()
    references = [Reference(title=r.get("title", "")[:120], url=r.get("url", ""),
                            snippet=(r.get("content") or "")[:400])
                  for r in data.get("results", []) if r.get("url", "").startswith("https://")]
    images = [ReferenceImage(url=i["url"], description=(i.get("description") or "")[:300])
              for i in data.get("images", []) if isinstance(i, dict) and i.get("description")
              and str(i.get("url", "")).startswith("https://")]  # undescribed photos are invisible to the text model
    return Research(references=references[:5], images=images[:4])


def prompt_block(research: Research) -> str:
    if not research.references and not research.images:
        return ""
    lines = ["Real robots that do this job (from a web search):"]
    lines += [f"- {r.title}: {r.snippet}" for r in research.references]
    lines += [f"- Photo {n}: {i.description}" for n, i in enumerate(research.images) if i.description]
    return "\n".join(lines)
