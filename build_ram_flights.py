#!/usr/bin/env python3
"""
VERSION 2 — Vols RAM depuis les archives ADSB.lol (licence ODbL).

Nouveautés :
- fl_max     : niveau de vol maximum (altitude max / 100)
- gs_max     : vitesse sol maximum (nœuds)
- squawk     : code transpondeur le plus utilisé pendant le vol
- dep / arr  : coordonnées [lat, lon] du premier et dernier point vu
- immatriculation de secours : si absente de la trace du jour,
  on la déduit du code hex via fleet_RAM.json (fini les "?")
- auto-réparation : une journée déjà présente mais à l'ancien format
  (ou avec des "?") est refaite automatiquement.

    python3 build_ram_flights.py 2025-08-01 2026-07-31
"""
import gzip, io, json, sys, tarfile, urllib.request, urllib.error
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "ram_flights.json"
FLEET = json.load(open(HERE / "fleet_RAM.json"))
FLEET_LOW = {k.lower(): v for k, v in FLEET.items()}
WANTED = {f"./traces/{h[-2:]}/trace_full_{h}.json" for h in FLEET_LOW}

BASE = ("https://github.com/adsblol/globe_history_{y}/releases/download/"
        "v{y}.{m:02d}.{d:02d}-planes-readsb-prod-0/"
        "v{y}.{m:02d}.{d:02d}-planes-readsb-prod-0.tar.{part}")


def stream(day):
    for part in ("aa", "ab", "ac", "ad"):
        url = BASE.format(y=day.year, m=day.month, d=day.day, part=part)
        try:
            r = urllib.request.urlopen(url, timeout=60)
        except urllib.error.HTTPError:
            return
        while chunk := r.read(1 << 20):
            yield chunk


class Reader(io.RawIOBase):
    def __init__(s, g): s.g, s.b = g, b""
    def readable(s): return True
    def readinto(s, out):
        while len(s.b) < len(out):
            try: s.b += next(s.g)
            except StopIteration: break
        n = min(len(out), len(s.b)); out[:n], s.b = s.b[:n], s.b[n:]; return n


def one_day(day):
    flights, remaining = {}, set(WANTED)
    try:
        tar = tarfile.open(fileobj=io.BufferedReader(Reader(stream(day)), 1 << 22), mode="r|")
    except tarfile.ReadError:
        return None  # archive absente
    for m in tar:
        if m.name not in remaining:
            continue
        remaining.discard(m.name)
        raw = tar.extractfile(m).read()
        try: d = json.loads(gzip.decompress(raw))
        except gzip.BadGzipFile: d = json.loads(raw)
        hexc = d.get("icao", "").lower()
        finfo = FLEET_LOW.get(hexc, ["?", "?"])
        reg = d.get("r") or finfo[0]          # secours via table flotte
        typ = d.get("t") or finfo[1]
        base = d.get("timestamp", 0)
        # agrégats par callsign
        agg = {}
        for p in d.get("trace", []):
            if not (len(p) > 8 and isinstance(p[8], dict) and p[8].get("flight")):
                continue
            cs = p[8]["flight"].strip()
            if not cs.startswith("RAM"):
                continue
            a = agg.setdefault(cs, {"ts": [], "alt": [], "gs": [],
                                    "sq": Counter(), "pts": []})
            ts = base + p[0]
            a["ts"].append(ts)
            if isinstance(p[3], (int, float)): a["alt"].append(p[3])
            if isinstance(p[4], (int, float)): a["gs"].append(p[4])
            if p[8].get("squawk"): a["sq"][p[8]["squawk"]] += 1
            if isinstance(p[1], (int, float)): a["pts"].append((ts, p[1], p[2]))
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")
        for cs, a in agg.items():
            first = min(a["pts"]) if a["pts"] else None
            last = max(a["pts"]) if a["pts"] else None
            flights[cs] = {
                "reg": reg, "type": typ,
                "from_utc": fmt(min(a["ts"])), "to_utc": fmt(max(a["ts"])),
                "fl_max": round(max(a["alt"]) / 100) if a["alt"] else None,
                "gs_max": round(max(a["gs"])) if a["gs"] else None,
                "squawk": a["sq"].most_common(1)[0][0] if a["sq"] else None,
                "dep": [round(first[1], 3), round(first[2], 3)] if first else None,
                "arr": [round(last[1], 3), round(last[2], 3)] if last else None,
            }
        if not remaining:
            break
    return flights


def needs_redo(day_data):
    """Vrai si la journée est vide, à l'ancien format, ou contient des '?'."""
    if not day_data:
        return True
    for v in day_data.values():
        if "fl_max" not in v or v.get("reg") in (None, "?"):
            return True
    return False


def main(start, end):
    data = json.load(open(OUT)) if OUT.exists() else {}
    day, end = date.fromisoformat(start), date.fromisoformat(end)
    while day <= end:
        key = day.isoformat()
        if key not in data or needs_redo(data[key]):
            print(f"{key} …", flush=True)
            res = one_day(day)
            data[key] = res if res is not None else {}
            print(f"  {'archive absente' if res is None else str(len(res)) + ' vols'}")
            json.dump(data, open(OUT, "w"), sort_keys=True)
        day += timedelta(days=1)
    print(f"Terminé -> {OUT} ({OUT.stat().st_size/1e6:.1f} Mo)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
