"""
HW7 Part 4: fetch a pricing page, extract its text, and cut it into short quotable snippets.

Every fetch is saved as an evidence snapshot (extracted text + raw HTML) with the source URL,
the access time and SHA-256 hashes, so a later change to the public page cannot change the
evidence behind a run. A run fetches each URL once and reuses that snapshot for every query.

Pricing pages often put prices in a comparison grid built from <div>s rather than a <table>
(the Bay Wheels page does). extract_snippets() pairs every grid cell with its column header
("Month pass - Classic bike prices: 45 min free, then $0.17/min") so a snippet still says which
plan a price belongs to; ordinary paragraphs are kept with their nearest heading.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

SNAPSHOT_DIR = os.path.join("reports", "hw07", "raw", "pricing_snapshots")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
PRICE_WORDS = re.compile(r"\$|\d|unlock|minute|/min|member|pass|ride|fee|free|overage", re.I)
MAX_SNIPPET_CHARS = 300


def sha256(text: str) -> str:
    """Hex SHA-256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_html(url: str) -> tuple[str, str]:
    """(html, final_url). Local fixtures can be given as file paths or file:// URLs."""
    if url.startswith("file://") or os.path.exists(url):
        path = url[len("file://") :] if url.startswith("file://") else url
        with open(path, encoding="utf-8") as f:
            return f.read(), path
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text, response.url


def _clean(text: str) -> str:
    """Collapse whitespace."""
    return re.sub(r"\s+", " ", text or "").strip()


def page_text(soup: BeautifulSoup) -> str:
    """Readable text of the page (one line per block), used for the snapshot and hashing."""
    root = soup.find("main") or soup.body or soup
    lines = [_clean(t) for t in root.get_text("\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _grid_snippets(soup: BeautifulSoup) -> list:
    """Pair each comparison-grid cell with its column header, then drop the grid from soup.

    Removing the grid afterwards stops its cells being picked up again as loose paragraphs
    under the wrong plan heading.
    """
    snippets = []
    for header_row in soup.find_all("div"):
        cols = [c for c in header_row.find_all("div", recursive=False)]
        heads = [
            _clean(c.find(["h2", "h3"]).get_text(" ")) if c.find(["h2", "h3"]) else "" for c in cols
        ]
        if len(cols) < 3 or sum(bool(h) for h in heads) < len(cols) - 1:
            continue
        scope = header_row.find_parent("section") or soup
        for row in scope.find_all("div"):
            cells = [_clean(c.get_text(" ")) for c in row.find_all("div", recursive=False)]
            if len(cells) != len(heads) or row is header_row or cells == heads:
                continue
            label = cells[0] or "Price"
            for head, cell in zip(heads[1:], cells[1:]):
                if head and cell and PRICE_WORDS.search(cell):
                    snippets.append(f"{head} - {label}: {cell}")
        if scope is not soup:
            scope.decompose()
        break  # one header row per page is enough; the grid repeats in mobile cards
    return snippets


def _block_snippets(soup: BeautifulSoup) -> list:
    """Paragraphs and list items that mention prices or rules, prefixed by their heading."""
    snippets = []
    for block in soup.find_all(["p", "li"]):
        text = _clean(block.get_text(" "))
        if len(text) < 4 or not PRICE_WORDS.search(text):
            continue
        heading = block.find_previous(["h1", "h2", "h3"])
        prefix = _clean(heading.get_text(" ")) if heading else ""
        snippet = f"{prefix}: {text}" if prefix and prefix not in text else text
        snippets.append(snippet[:MAX_SNIPPET_CHARS])
    return snippets


def extract_snippets(html: str) -> tuple[list, str]:
    """(unique snippets, page text) from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript", "template"]):
        tag.decompose()
    seen, unique = set(), []
    for s in _grid_snippets(soup) + _block_snippets(soup):
        if s.lower() not in seen:
            seen.add(s.lower())
            unique.append(s)
    return unique, page_text(soup)


def save_snapshot(url: str, final_url: str, html: str, text: str, snippets: list) -> dict:
    """Write text + HTML + metadata (URL, access time, SHA-256) and return the metadata."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    meta = {
        "url": url,
        "final_url": final_url,
        "accessed_utc": now.isoformat(timespec="seconds"),
        "sha256_text": sha256(text),
        "sha256_html": sha256(html),
        "text_chars": len(text),
        "html_bytes": len(html.encode("utf-8")),
        "snippet_count": len(snippets),
        "text_file": os.path.join(SNAPSHOT_DIR, f"pricing_{stamp}.txt"),
        "html_file": os.path.join(SNAPSHOT_DIR, f"pricing_{stamp}.html"),
    }
    with open(meta["text_file"], "w", encoding="utf-8") as f:
        f.write(text)
    with open(meta["html_file"], "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(SNAPSHOT_DIR, f"pricing_{stamp}.json"), "w") as f:
        json.dump({**meta, "snippets": snippets}, f, indent=2)
    return meta


class PricingSnapshotCache:
    """One snapshot per URL per run, so every query in a run quotes the same captured page."""

    def __init__(self, save: bool = True):
        self.save = save
        self._pages: dict = {}

    def get(self, url: str) -> dict:
        """{snippets, text, meta} for url, fetching and snapshotting it on first use."""
        if url not in self._pages:
            html, final_url = fetch_html(url)
            snippets, text = extract_snippets(html)
            meta = (
                save_snapshot(url, final_url, html, text, snippets)
                if self.save
                else {
                    "url": url,
                    "final_url": final_url,
                    "sha256_text": sha256(text),
                    "accessed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            )
            self._pages[url] = {"snippets": snippets, "text": text, "meta": meta}
        return self._pages[url]


def rank(snippets: list, query: str, k: int) -> list:
    """Top-k snippets by query-term overlap.

    Rarer terms weigh more, each query word pair found in a snippet ("month pass") adds 1,
    long snippets are damped, and ties keep page order.
    """
    words = re.findall(r"[a-z0-9$.]+", query.lower())
    terms = [t for t in words if len(t) > 2 or t == "$"]
    pairs = [f"{a} {b}" for a, b in zip(words, words[1:])]
    lowered = [s.lower() for s in snippets]
    weights = {t: 1.0 / (1 + sum(t in s for s in lowered)) for t in set(terms)}
    scored = []
    for i, (s, low) in enumerate(zip(snippets, lowered)):
        overlap = sum(w for t, w in weights.items() if t in low)
        bonus = sum(1.0 for p in pairs if p in low) + (0.2 if "$" in s else 0.0)
        score = (overlap + bonus) / (1 + len(s) / 200) if overlap else 0
        if score > 0:
            scored.append((round(score, 3), i, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"text": s, "score": score} for score, _, s in scored[:k]]


def find_snapshot(sha: Optional[str] = None) -> list:
    """Saved snapshot metadata files (newest first), optionally filtered by text hash."""
    if not os.path.isdir(SNAPSHOT_DIR):
        return []
    metas = []
    for name in sorted(os.listdir(SNAPSHOT_DIR), reverse=True):
        if name.endswith(".json"):
            with open(os.path.join(SNAPSHOT_DIR, name)) as f:
                meta = json.load(f)
            if sha is None or meta["sha256_text"] == sha:
                metas.append(meta)
    return metas
