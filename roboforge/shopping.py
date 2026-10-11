"""Where to buy each part: product pages at known robotics retailers (Tavily web search).

Prices come from search snippets, so they are only shown when they look like this
part's price (close to the catalog estimate) and must be checked on the store page.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urlparse

import httpx
from pydantic import BaseModel

from roboforge.models import RobotProject
from roboforge.research import TAVILY_URL

STORES = {"robotshop.com": "RobotShop", "amazon.com": "Amazon", "pololu.com": "Pololu", "sparkfun.com": "SparkFun",
          "adafruit.com": "Adafruit", "digikey.com": "DigiKey", "mouser.com": "Mouser", "servocity.com": "ServoCity",
          "gobilda.com": "goBILDA", "seeedstudio.com": "Seeed Studio", "aliexpress.com": "AliExpress"}
NOT_PRODUCT = ("/s?", "/s/", "/search", "/category", "/categories", "/collections", "/stores/", "/clp/", "/w/",
               "/file", "datasheet", ".pdf", "/wiki", "/blog", "/forum", "/resources", "/reviews")
PRICE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)(?!\d)")
FOREIGN_LOCALE = re.compile(r"^/(?!en\b|us\b)[a-z]{2}(?:-[a-z]{2})?/", re.I)  # e.g. /es/, /fr-ca/
FILLER = {"and", "with", "the", "for", "kit", "set", "pair", "unit", "mm", "in"}
ONE_STOP_SLACK = 1.15  # pay up to 15% more to keep a part at the main store

_offers: dict[str, list[dict]] = {}


class Offer(BaseModel):
    store: str
    url: str
    title: str = ""
    price_usd: float | None = None


def _store(url: str) -> str | None:
    host = (urlparse(url).hostname or "").removeprefix("www.")
    return STORES.get(host)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+(?:\.[0-9]+[a-z]*)?", text.lower()))


def _same_part(name: str, title: str, url: str) -> bool:
    """Model codes (S2, DCX22, 40Ah) must all match; most other words must too."""
    want, have = _tokens(name), _tokens(f"{title} {url.replace('-', ' ')}")
    models = {t for t in want if re.search(r"\d", t) and re.search(r"[a-z]", t)}
    words = {t for t in want - models if len(t) > 1 and not t.isdigit() and t not in FILLER}
    if not models <= have:
        return False
    hits = sum(1 for t in words if t in have or f"{t}s" in have)
    return hits * 2 >= len(words) if models else hits * 3 >= len(words) * 2


def _price(text: str, estimate: float) -> float | None:
    prices = [float(p.replace(",", "")) for p in PRICE.findall(text)]
    plausible = [p for p in prices if 0.4 * estimate <= p <= 2.5 * estimate]
    return min(plausible) if plausible else None


def find_offers(name: str, estimate: float) -> list[Offer]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        return []
    for _ in range(2):  # one retry: parallel searches occasionally hit the rate limit
        if name in _offers:
            break
        try:
            response = httpx.post(TAVILY_URL, timeout=20, headers={"Authorization": f"Bearer {key}"},
                                  json={"query": f"buy {name}", "max_results": 8, "include_domains": list(STORES)})
            response.raise_for_status()
            results = response.json().get("results", [])
        except (httpx.HTTPError, ValueError):
            continue
        _offers[name] = [r for r in results if isinstance(r, dict) and str(r.get("url", "")).startswith("https://")]
    offers, seen = [], set()
    for r in _offers.get(name, []):
        url, store, title = r["url"], _store(r["url"]), r.get("title") or ""
        path = urlparse(url).path
        if not store or store in seen or path in ("", "/") or FOREIGN_LOCALE.match(path) \
                or any(bad in url.lower() for bad in NOT_PRODUCT) or not _same_part(name, title, url):
            continue
        seen.add(store)
        offers.append(Offer(store=store, url=url, title=title[:120],
                            price_usd=_price(r.get("content") or "", estimate)))
    return offers


def where_to_buy(project: RobotProject) -> dict:
    """One link per bought part, keeping as many as reasonable at a single store."""
    bought = [c for c in project.components if c.source != "generated"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        found = list(pool.map(lambda c: find_offers(c.name, c.unit_cost_usd), bought))
    coverage: dict[str, int] = {}
    for offers in found:
        for o in offers:
            coverage[o.store] = coverage.get(o.store, 0) + 1
    main = max(coverage, key=lambda s: (coverage[s], -list(STORES.values()).index(s)), default=None)
    lines = []
    for c, offers in zip(bought, found):
        at_main = next((o for o in offers if o.store == main), None)
        priced = [o for o in offers if o.price_usd is not None]
        cheapest = min(priced, key=lambda o: o.price_usd, default=None)
        pick = at_main
        main_price = (at_main.price_usd if at_main else None) or c.unit_cost_usd
        if cheapest and (not at_main or main_price > cheapest.price_usd * ONE_STOP_SLACK):
            pick = cheapest
        pick = pick or (offers[0] if offers else None)
        lines.append({"component_id": c.id, "name": c.name, "quantity": c.quantity, "estimate_usd": c.unit_cost_usd,
                      "offer": pick.model_dump() if pick else None,
                      "search_url": None if pick else f"https://www.amazon.com/s?k={quote_plus(c.name)}",
                      "others": [o.model_dump() for o in offers if o is not pick][:2]})
    picked: dict[str, int] = {}
    for line in lines:
        if line["offer"]:
            picked[line["offer"]["store"]] = picked.get(line["offer"]["store"], 0) + 1
    main = max(picked, key=lambda s: (picked[s], s == main), default=None)
    return {"main_store": main, "at_main_store": picked.get(main, 0), "bought_parts": len(bought),
            "printed_parts": len(project.components) - len(bought), "lines": lines}
