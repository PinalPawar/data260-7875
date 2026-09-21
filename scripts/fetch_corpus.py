"""
Fills out the HW3 domain corpus (DOMAIN_ID 3, Grocery supply and recall
notices) to 200KB+ of local files in corpus/, using two real, public
sources:

  1. A curated list of additional FDA/USDA(FSIS)/CDC recall & outbreak
     pages -- readable prose, good material for writing/answering the
     5 questions in questions.yaml.
  2. The public openFDA Food Enforcement API -- a reliable, official,
     structured source of many recall records at once. This is what
     comfortably clears the 200KB minimum without needing dozens of
     one-off page fetches.

26 files are already in corpus/ (gathered earlier, ~33KB) -- this script
adds to them and does NOT overwrite existing files.

IMPORTANT: this needs a normal, unrestricted internet connection, so run it
on your own machine, not inside a locked-down sandbox. Safe to re-run.

    pip install -r requirements.txt
    python3 scripts/fetch_corpus.py
"""
import hashlib
import json
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
CORPUS_DIR.mkdir(exist_ok=True)
ACCESS_DATE = date.today().isoformat()
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DATA260-HW3-corpus-tool/1.0"}

# ---- 1) additional narrative pages (readable prose) ----------------------
NARRATIVE_PAGES = [
    ("fsis_meat_poultry_dairy_salmonella_2026.txt",
     "https://www.fsis.usda.gov/recalls-alerts/fsis-issues-public-health-alert-various-meat-and-poultry-products-containing-fda"),
    ("fsis_meat_poultry_jalapenos_salmonella_2026.txt",
     "https://www.fsis.usda.gov/recalls-alerts/fsis-issues-public-health-alert-various-meat-and-poultry-products-containing-fda-0"),
    ("fsis_ground_beef_ecoli_2026.txt",
     "https://www.fsis.usda.gov/recalls-alerts/mountain-west-food-group-llc-recalls-ground-beef-products-due-possible-e--coli-o26"),
    ("fsis_headcheese_listeria.txt",
     "https://www.fsis.usda.gov/recalls-alerts/fsis-issues-public-health-alert-headcheese-deli-meat-products-may-be-contaminated"),
    ("fsis_chicken_fried_rice_foreign_matter.txt",
     "https://www.fsis.usda.gov/recalls-alerts/ajinomoto-foods-north-america-inc--recalls-chicken-fried-rice-products-due-0"),
    ("fsis_chicken_caesar_wrap_listeria.txt",
     "https://www.fsis.usda.gov/recalls-alerts/fsis-issues-public-health-alert-ready-eat-chicken-caesar-wrap-products-may-be"),
    ("fsis_buffalo_chicken_uninspected.txt",
     "https://www.fsis.usda.gov/recalls-alerts/shanghai-ravioli-corporation-recalls-not-ready-eat-frozen-buffalo-chicken-products"),
    ("fda_outbreak_ecoli_spinach_2021.txt",
     "https://www.fda.gov/food/outbreaks-foodborne-illness/outbreak-investigation-e-coli-o157h7-spinach-november-2021"),
    ("fda_outbreak_salmonella_cantaloupes_2023.txt",
     "https://www.fda.gov/food/outbreaks-foodborne-illness/outbreak-investigation-salmonella-cantaloupes-november-2023"),
    ("fda_recall_cantaloupes_2023.txt",
     "https://www.fda.gov/safety/major-product-recalls/2023-recalls-food-products-associated-cantaloupes-due-potential-risk-salmonella"),
    ("fda_recall_peanut_butter_smucker_2022.txt",
     "https://www.fda.gov/safety/major-product-recalls/2022-recalls-food-products-associated-peanut-butter-jm-smucker-company-due-potential-risk-salmonella"),
    ("fda_outbreaks_investigations_index.txt",
     "https://www.fda.gov/food/outbreaks-foodborne-illness/investigations-foodborne-illness-outbreaks"),
]


def html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def save_doc(filename, url, title, body):
    header = f"Source: {url}\nAccessed: {ACCESS_DATE}\nTitle: {title}\n\n"
    (CORPUS_DIR / filename).write_text(header + body.strip() + "\n", encoding="utf-8")


def fetch_narrative_pages():
    for filename, url in NARRATIVE_PAGES:
        out_path = CORPUS_DIR / filename
        if out_path.exists():
            print(f"  already have {filename}, skipping")
            continue
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            text = html_to_text(resp.text)
            title = url.rstrip("/").split("/")[-1].replace("-", " ")
            save_doc(filename, url, title, text[:20000])
            print(f"  saved {filename} ({len(text)} chars)")
        except Exception as e:
            print(f"  SKIP {url}: {e}")
        time.sleep(0.5)


# ---- 2) bulk openFDA enforcement records ----------------------------------
# Official public API: https://open.fda.gov/apis/food/enforcement/
# Two broad queries at the max page size (1000) are already far more than
# enough to clear 200KB on their own.
OPENFDA_QUERIES = ['classification:"Class I"', 'classification:"Class II"']


def fetch_openfda_bulk():
    all_records = {}
    for q in OPENFDA_QUERIES:
        try:
            resp = requests.get(
                "https://api.fda.gov/food/enforcement.json",
                params={"search": q, "limit": 1000},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            for rec in results:
                key = rec.get("recall_number") or rec.get("event_id") or str(len(all_records))
                all_records[key] = rec
            print(f"  openFDA query {q!r}: {len(results)} records")
        except Exception as e:
            print(f"  SKIP openFDA query {q!r}: {e}")
        time.sleep(0.3)

    if not all_records:
        print("  openFDA fetch returned nothing (check your internet connection) -- skipping bulk file.")
        return

    lines = []
    for rec in all_records.values():
        lines.append(
            f"Recall #{rec.get('recall_number', '?')} | {rec.get('classification', '?')} | "
            f"Firm: {rec.get('recalling_firm', '?')} ({rec.get('city', '?')}, {rec.get('state', '?')}) | "
            f"Initiated: {rec.get('recall_initiation_date', '?')} | "
            f"Product: {rec.get('product_description', '?')} | "
            f"Reason: {rec.get('reason_for_recall', '?')} | "
            f"Distribution: {rec.get('distribution_pattern', '?')}"
        )
    body = "\n\n".join(lines)
    save_doc(
        "openfda_enforcement_bulk_records.txt",
        "https://api.fda.gov/food/enforcement.json (openFDA public Food Enforcement API)",
        "openFDA Food Enforcement Records (bulk snapshot, Class I & II)",
        body,
    )
    print(f"  saved openfda_enforcement_bulk_records.txt ({len(all_records)} records, {len(body)} chars)")


# ---- 3) rebuild SOURCES.md + CORPUS_MANIFEST.json from corpus/*.txt ------
def rebuild_sources_and_manifest():
    manifest = []
    sources_lines = [
        "# SOURCES.md\n",
        "Domain: Grocery supply and recall notices (DOMAIN_ID 3)\n",
        "Auto-generated by `scripts/fetch_corpus.py` from each file's own citation header.\n",
        "| File | Source URL | Accessed |",
        "|---|---|---|",
    ]
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        lines = text.split("\n")
        url = accessed = "unknown"
        if lines and lines[0].startswith("Source:"):
            url = lines[0][len("Source:"):].strip()
        if len(lines) > 1 and lines[1].startswith("Accessed:"):
            accessed = lines[1][len("Accessed:"):].strip()
        manifest.append(
            {
                "filename": path.name,
                "byte_size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_url": url,
                "accessed": accessed,
            }
        )
        sources_lines.append(f"| {path.name} | {url} | {accessed} |")

    (ROOT / "SOURCES.md").write_text("\n".join(sources_lines) + "\n", encoding="utf-8")
    (ROOT / "CORPUS_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    total_bytes = sum(m["byte_size"] for m in manifest)
    print(f"\n{len(manifest)} corpus files, {total_bytes} bytes ({total_bytes / 1024:.1f} KB) total.")
    if total_bytes < 200 * 1024:
        print("STILL UNDER 200KB -- just re-run this script again (it's safe/idempotent); the openFDA")
        print("pull alone should push this well past 200KB once your internet connection is used.")
    else:
        print("200KB+ requirement met.")
    print("Wrote SOURCES.md and CORPUS_MANIFEST.json")


def main():
    print("Fetching additional narrative recall/outbreak pages...")
    fetch_narrative_pages()
    print("\nFetching bulk openFDA enforcement records...")
    fetch_openfda_bulk()
    print("\nRebuilding SOURCES.md and CORPUS_MANIFEST.json from corpus/*.txt ...")
    rebuild_sources_and_manifest()


if __name__ == "__main__":
    main()
