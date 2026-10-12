#!/usr/bin/env python3
"""Refresh public INKs marketplace stats.

This intentionally uses public pages only: no wallet credentials, cookies, or
session tokens. Missing values remain null. ORD.NET's documented API requires
wallet authentication, so this collector does not call it anonymously.
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
    "User-Agent": "INKs-onChain-MarketStatusBot/1.1 (+https://github.com/Inksonchain/INKs-onchain)",
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

def clean_num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    raw = str(value).strip().replace(",", "")
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return None

def walk_json(value, found):
    if isinstance(value, dict):
        for key, val in value.items():
            k = re.sub(r"[^a-z]", "", str(key).lower())
            if isinstance(val, (str, int, float)) and not isinstance(val, bool):
                if k in ("floor", "floorprice", "floorpricesats", "lowestprice", "lowestlistingprice"):
                    found.setdefault("floor_raw", val)
                elif k in ("listedcount", "listed", "listingcount", "numberlisted", "listeditems"):
                    found.setdefault("listed_raw", val)
                elif k in ("volume", "totalvolume", "volumeinbtc", "totalbtc"):
                    found.setdefault("volume_raw", val)
                elif k in ("ownercount", "owners", "collectorcount", "holders", "holdercount"):
                    found.setdefault("owners_raw", val)
                elif k in ("onedaychange", "change24h", "percentchange24h", "24hchange"):
                    found.setdefault("change24h_raw", val)
                elif k in ("sevendaychange", "change7d", "percentchange7d", "7dchange"):
                    found.setdefault("change7d_raw", val)
                elif k in ("sevendayvolume", "volume7d", "7dvolume"):
                    found.setdefault("volume7d_raw", val)
                elif k in ("supply", "totalsupply", "collectionsize"):
                    found.setdefault("supply_raw", val)
                elif k in ("marketcap", "marketcapbtc", "marketcapitalization"):
                    found.setdefault("marketcap_raw", val)
                elif k in ("ownerpercent", "holderspercent", "ownershippercent"):
                    found.setdefault("owner_percent_raw", val)
                elif k in ("currency", "symbol", "denomination"):
                    found.setdefault("currency", str(val))
            walk_json(val, found)
    elif isinstance(value, list):
        for item in value:
            walk_json(item, found)

def first_match(patterns, text, flags=re.I):
    for pattern in patterns:
        m = re.search(pattern, text, flags)
        if m:
            return m
    return None

def parse_page(url):
    html = fetch(url)
    parser = TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    found = {}

    # Parse JSON-bearing scripts (JSON-LD and framework state where available).
    for chunk in parser.scripts:
        chunk = chunk.strip()
        if not chunk or len(chunk) > 2_000_000:
            continue
        candidates = [chunk]
        match = re.search(r"\{.*\}", chunk, re.S)
        if match:
            candidates.append(match.group(0))
        for candidate in candidates:
            try:
                walk_json(json.loads(candidate), found)
                break
            except Exception:
                pass

    # Public rendered-text fallbacks. Em dashes/empty values deliberately stay null.
    if "listed_raw" not in found:
        m = first_match([r"\bListed\s+(?:items?\s*)?(\d[\d,]*)\b"], text)
        if m:
            found["listed_raw"] = m.group(1).replace(",", "")

    if "floor_raw" not in found:
        m = first_match([
            r"(?:Floor\s+price|Floor|Lowest\s+price)\s*[:：]?\s*(\d[\d,]*(?:\.\d+)?)\s*(BTC|SATS?|₿)?",
            r"(\d+(?:\.\d+)?)\s*BTC\s*(?:floor|floor price)",
        ], text)
        if m:
            found["floor_raw"] = m.group(1).replace(",", "")
            if len(m.groups()) > 1 and m.group(2):
                found["currency"] = m.group(2).upper()

    # Ord.net's public listing cards expose prices followed by "Buy". If the
    # collection header has no floor value, infer a floor only from those prices.
    if found.get("floor_raw") is None and "ord.net/collection/" in url:
        prices = [int(x.replace(",", "")) for x in re.findall(r"\b(\d{1,3}(?:,\d{3})+|\d{4,})\s*(?:sats?\s*)?Buy\b", text, re.I)]
        if prices:
            found["floor_raw"] = min(prices)
            found["floor_inferred_from_listings"] = True
            found["currency"] = "sats"

    if "volume_raw" not in found:
        m = first_match([
            r"\bTotal\s+(\d+(?:\.\d+)?)\s*(BTC|₿)?",
            r"\b(?:Total\s+volume|Volume)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(BTC|₿)?",
        ], text)
        if m:
            found["volume_raw"] = m.group(1)
            if len(m.groups()) > 1 and m.group(2):
                found["volume_currency"] = "BTC"

    if "owners_raw" not in found:
        m = first_match([r"\bOwners?\s+(\d[\d,]*)\b", r"\bCollectors?\s+(\d[\d,]*)\b"], text)
        if m:
            found["owners_raw"] = m.group(1).replace(",", "")

    if "owner_percent_raw" not in found:
        m = first_match([r"\bOwners?\s+\d[\d,]*\s*\((\d+(?:\.\d+)?)%\)", r"\b(\d+(?:\.\d+)?)%\s*(?:of\s+)?owners?\b"], text)
        if m:
            found["owner_percent_raw"] = m.group(1)

    if "change24h_raw" not in found:
        m = first_match([r"\b24H\s+([+\-]?\d+(?:\.\d+)?%)", r"\b24h\s+(?:change\s+)?([+\-]?\d+(?:\.\d+)?%)"], text)
        if m:
            found["change24h_raw"] = m.group(1).replace("%", "")

    floor = found.get("floor_raw")
    listed = clean_num(found.get("listed_raw"))
    volume = found.get("volume_raw")
    owners = clean_num(found.get("owners_raw"))
    owner_percent = clean_num(found.get("owner_percent_raw"))
    change24h = clean_num(found.get("change24h_raw"))
    change7d = clean_num(found.get("change7d_raw"))
    volume7d = found.get("volume7d_raw")
    supply = clean_num(found.get("supply_raw"))
    market_cap = clean_num(found.get("marketcap_raw"))

    result = {
        "status": "partial",
        "source": url,
        "floor": None,
        "floorUnit": None,
        "floorDerived": bool(found.get("floor_inferred_from_listings")),
        "listed": int(listed) if listed is not None else None,
        "volume": str(volume) if volume is not None else None,
        "volumeUnit": found.get("volume_currency", "BTC" if volume is not None and re.search(r"\bTotal\s+\d+\.\d+", text, re.I) else None),
        "change24h": change24h,
        "change7d": change7d,
        "volume7d": str(volume7d) if volume7d is not None else None,
        "volume7dUnit": found.get("volume7d_currency"),
        "supply": int(supply) if supply is not None else None,
        "marketCap": market_cap,
        "owners": int(owners) if owners is not None else None,
        "ownerPercent": owner_percent,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    if floor is not None:
        result["floor"] = clean_num(floor)
        currency = str(found.get("currency", "")).lower()
        result["floorUnit"] = "sats" if "sat" in currency or found.get("floor_inferred_from_listings") else ("BTC" if "btc" in currency or currency == "₿" else currency or None)

    if any(result[k] is not None for k in ("floor", "listed", "volume", "change24h", "change7d", "volume7d", "supply", "marketCap", "owners")):
        result["status"] = "partial" if any(result[k] is None for k in ("floor", "listed")) else "ok"
    else:
        result["status"] = "unavailable"
        result["note"] = "No public extractable stats found; source may require authentication or its markup may have changed."
    return result

def main():
    data = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "marketplaces": {},
        "feedVersion": 2,
        "note": "Publicly extracted stats only. Null means unavailable; floorDerived indicates a floor inferred from visible listing prices."
    }
    for market, url in SOURCES.items():
        try:
            data["marketplaces"][market] = parse_page(url)
            print(market + ": " + data["marketplaces"][market]["status"])
        except Exception as exc:
            data["marketplaces"][market] = {
                "status": "unavailable", "source": url, "floor": None,
                "floorUnit": None, "floorDerived": False, "listed": None,
                "volume": None, "volumeUnit": None, "change24h": None,
                "change7d": None, "volume7d": None, "volume7dUnit": None,
                "supply": None, "marketCap": None,
                "owners": None, "ownerPercent": None,
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
