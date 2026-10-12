#!/usr/bin/env python3
"""Refresh public INKs marketplace stats from publicly accessible collection pages.

Only publishes values actually found in page metadata/embedded JSON. No credentials
or wallet signatures are used. If a source blocks scraping or changes its markup,
its status is marked unavailable rather than inventing numbers.
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

OUT = "data/market-status.json"
SOURCES = {
    "satflow": "https://www.satflow.com/ordinals/inks",
    "ordnet": "https://ord.net/collection/inks",
    "orddropz": "https://ord-dropz.xyz/secondary/collections/inks",
}
HEADERS = {
    "User-Agent": "INKs-onChain-MarketStatusBot/1.0 (+https://github.com/Inksonchain/INKs-onchain)",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.in_script = False
        self.scripts = []
        self.current_script = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.in_script = True
            self.current_script = []
    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.in_script:
            self.scripts.append("".join(self.current_script))
            self.in_script = False
        elif tag.lower() in ("p", "div", "span", "li", "h1", "h2", "h3", "br"):
            self.parts.append(" ")
    def handle_data(self, data):
        if self.in_script:
            self.current_script.append(data)
        else:
            self.parts.append(data)

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError("HTTP " + str(response.status))
        return response.read(5_000_000).decode("utf-8", "replace")

def walk_json(value, found):
    if isinstance(value, dict):
        for key, val in value.items():
            k = re.sub(r"[^a-z]", "", str(key).lower())
            if isinstance(val, (str, int, float)) and not isinstance(val, bool):
                if k in ("floor", "floorprice", "floorpricesats", "lowestprice", "lowestlistingprice"):
                    found.setdefault("floor_raw", val)
                elif k in ("listedcount", "listed", "listingcount", "numberlisted", "listeditems"):
                    found.setdefault("listed_raw", val)
                elif k in ("sevendayvolume", "volume7d", "volume", "totalvolume", "volumeinbtc"):
                    found.setdefault("volume_raw", val)
                elif k in ("currency", "symbol", "denomination"):
                    found.setdefault("currency", str(val))
            walk_json(val, found)
    elif isinstance(value, list):
        for item in value:
            walk_json(item, found)

def parse_page(url):
    html = fetch(url)
    parser = TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    found = {}
    # Parse JSON-bearing script tags (Next.js state, JSON-LD, application/json).
    for chunk in parser.scripts:
        chunk = chunk.strip()
        if not chunk or len(chunk) > 2_000_000:
            continue
        candidates = [chunk]
        # Some apps wrap JSON in JavaScript assignments; try the first JSON object.
        match = re.search(r"\{.*\}", chunk, re.S)
        if match:
            candidates.append(match.group(0))
        for candidate in candidates:
            try:
                walk_json(json.loads(candidate), found)
                break
            except Exception:
                pass

    # Text fallback only accepts clearly-labelled figures.
    if "listed_raw" not in found:
        m = re.search(r"\bListed\s+(?:items?\s*)?(\d[\d,]*)\b", text, re.I)
        if m:
            found["listed_raw"] = m.group(1).replace(",", "")
    if "floor_raw" not in found:
        patterns = [
            r"(?:Floor\s+price|Floor|Lowest\s+price)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(BTC|SATS?|₿)?",
            r"(\d+(?:\.\d+)?)\s*BTC\s*(?:floor|floor price)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.I)
            if m:
                found["floor_raw"] = m.group(1)
                if len(m.groups()) > 1 and m.group(2):
                    found["currency"] = m.group(2).upper()
                break

    result = {"status": "partial", "source": url}
    floor = found.get("floor_raw")
    listed = found.get("listed_raw")
    volume = found.get("volume_raw")
    if floor is not None:
        result["floor"] = str(floor) + ((" " + found["currency"]) if found.get("currency") else "")
    else:
        result["floor"] = None
    try:
        result["listed"] = int(str(listed).replace(",", "")) if listed is not None else None
    except (TypeError, ValueError):
        result["listed"] = None
    result["volume"] = str(volume) if volume is not None else None
    if any(result[k] is not None for k in ("floor", "listed", "volume")):
        result["status"] = "ok" if all(result[k] is not None for k in ("floor", "listed", "volume")) else "partial"
    else:
        result["status"] = "unavailable"
        result["note"] = "No public stats found in page metadata; source may require API access or changed markup."
    result["checkedAt"] = datetime.now(timezone.utc).isoformat()
    return result

def main():
    data = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "marketplaces": {},
        "feedVersion": 1,
        "note": "Values are scraped from public pages only; null means not publicly extractable."
    }
    for market, url in SOURCES.items():
        try:
            data["marketplaces"][market] = parse_page(url)
            print(market + ": " + data["marketplaces"][market]["status"])
        except Exception as exc:
            data["marketplaces"][market] = {
                "status": "unavailable",
                "source": url,
                "floor": None,
                "listed": None,
                "volume": None,
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "note": str(exc)[:240],
            }
            print(market + ": unavailable (" + str(exc)[:120] + ")")
        time.sleep(1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

if __name__ == "__main__":
    main()
