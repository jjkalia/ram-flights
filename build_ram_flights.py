#!/usr/bin/env python3
"""
VERSION 3 — Vols RAM depuis les archives ADSB.lol (licence ODbL).

Changement majeur : au lieu de ne regarder que les 64 avions de la table
de flotte, on scanne TOUS les avions du monde et on garde ceux qui
émettent un callsign RAM + chiffre (RAM800F oui, RAMP1/RAMBO non).
=> attrape automatiquement les ATR de RAM Express, les avions loués
   (wet-lease, ex: A330 CS-TGD) et toute nouvelle livraison, pour toujours.

La table fleet_RAM.json ne sert plus que de secours pour l'immatriculation
quand elle manque dans la trace du jour.

    python3 build_ram_flights.py 2025-08-01 2026-07-31
"""
import gzip, io, json, sys, tarfile, urllib.request, urllib.error
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "ram_flights.json"
try:
    FLEET_LOW = {k.lower(): v for k, v in json.load(open(HERE / "fleet_RAM.json")).items()}
except FileNotFoundError:
    FLEET_LOW = {}

VERSION = 4


def is_ram_reg(reg):
    """Immatriculation de la famille RAM : CN-R.. (RAM), CN-CO.. (Express),
    CN-MAX/MAY, ou avion étranger (loué) — exclut hélicos/écoles CN-BZ, CN-PL…"""
    r = str(reg).upper().replace("-", "")
    return r.startswith(("CNR", "CNCO", "CNMA"))


def keep_entry(cs, reg):
    if cs.startswith("RAM"):
        return True            # callsign RAM : on garde (y compris avion loué)
    return is_ram_reg(reg)     # callsign immat : seulement la famille RAM


def clean_v3(day_data):
    """Migration v3 -> v4 sans re-téléchargement : retire le bruit."""
    out = {k: v for k, v in day_data.items()
           if k != "_v" and keep_entry(k, v.get("reg", ""))}
    out["_v"] = VERSION
    return out

BASE = ("https://github.com/adsblol/globe_history_{y}/releases/download/"
        "v{y}.{m:02d}.{d:02d}-planes-readsb-prod-0/"
        "v{y}.{m:02d}.{d:02d}-planes-readsb-prod-0.tar.{part}")


def stream(day):
    import time
    for part in ("aa", "ab", "ac", "ad"):
        url = BASE.format(y=day.year, m=day.month, d=day.day, part=part)
        offset, attempts = 0, 0
        while True:
            try:
                req = urllib.request.Request(url)
                if offset:
                    req.add_header("Range", f"bytes={offset}-")
                r = urllib.request.urlopen(req, timeout=90)
                skip = offset if (offset and r.status == 200) else 0
                while chunk := r.read(1 << 20):
                    if skip:
                        drop = min(skip, len(chunk))
                        chunk, skip = chunk[drop:], skip - drop
                        if not chunk:
                            continue
                    offset += len(chunk)
                    yield chunk
                break  # partie terminée, passer à la suivante
            except urllib.error.HTTPError as e:
                if e.code in (404, 416):
                    return  # plus de parties
                attempts += 1
            except Exception:
                attempts += 1  # coupure réseau : on réessaie au même octet
            if attempts >= 5:
                raise RuntimeError(f"réseau instable sur {url}")
            time.sleep(5 * attempts)


class Reader(io.RawIOBase):
    def __init__(s, g): s.g, s.b = g, b""
    def readable(s): return True
    def readinto(s, out):
        while len(s.b) < len(out):
            try: s.b += next(s.g)
            except StopIteration: break
        n = min(len(out), len(s.b)); out[:n], s.b = s.b[:n], s.b[n:]; return n


def is_ram(cs):
    # RAM + chiffre (vols normaux, charters, mises en place numérotées)
    if cs.startswith("RAM") and len(cs) > 3 and cs[3].isdigit():
        return True
    # immatriculation marocaine émise comme callsign (convoyages) : CNRGC, CN-RGC…
    c = cs.replace("-", "")
    return c.startswith("CN") and 4 <= len(c) <= 6


def one_day(day):
    flights = {}
    try:
        tar = tarfile.open(fileobj=io.BufferedReader(Reader(stream(day)), 1 << 22), mode="r|")
    except tarfile.ReadError:
        return None  # archive absente
    got_data = False
    for m in tar:
        if not (m.name.startswith("./traces/") and m.isfile()):
            continue
        f = tar.extractfile(m)
        if f is None:
            continue
        raw = f.read()
        got_data = True
        try:
            data = gzip.decompress(raw)
        except Exception:
            data = raw
        if b'"flight":"RAM' not in data and b'"flight":"CN' not in data:
            continue   # tri rapide avant parsing
        d = json.loads(data)
        hexc = d.get("icao", "").lower()
        finfo = FLEET_LOW.get(hexc, [None, None])
        reg = d.get("r") or finfo[0] or hexc.upper()
        typ = d.get("t") or finfo[1] or "?"
        base = d.get("timestamp", 0)
        agg = {}
        for p in d.get("trace", []):
            if not (len(p) > 8 and isinstance(p[8], dict) and p[8].get("flight")):
                continue
            cs = p[8]["flight"].strip()
            if not is_ram(cs):
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
            if not keep_entry(cs, reg):
                continue
            first = min(a["pts"]) if a["pts"] else None
            last = max(a["pts"]) if a["pts"] else None
            rec = {
                "reg": reg, "type": typ,
                "from_utc": fmt(min(a["ts"])), "to_utc": fmt(max(a["ts"])),
                "fl_max": round(max(a["alt"]) / 100) if a["alt"] else None,
                "gs_max": round(max(a["gs"])) if a["gs"] else None,
                "squawk": a["sq"].most_common(1)[0][0] if a["sq"] else None,
                "dep": [round(first[1], 3), round(first[2], 3)] if first else None,
                "arr": [round(last[1], 3), round(last[2], 3)] if last else None,
            }
            # si le même callsign apparaît sur 2 avions (rare), garder le plus long
            old = flights.get(cs)
            if old is None or (rec["to_utc"] > rec["from_utc"]):
                flights[cs] = rec
    if not got_data:
        return None
    flights["_v"] = VERSION   # marqueur de version de la journée
    return flights


def needs_redo(day_data):
    return not day_data or day_data.get("_v") != VERSION


def main(start, end):
    data = json.load(open(OUT)) if OUT.exists() else {}
    day, end = date.fromisoformat(start), date.fromisoformat(end)
    while day <= end:
        key = day.isoformat()
        if key in data and isinstance(data[key], dict) and data[key].get("_v") == 3:
            data[key] = clean_v3(data[key])          # migration rapide v3 -> v4
            json.dump(data, open(OUT, "w"), sort_keys=True)
        elif key not in data or needs_redo(data[key]):
            print(f"{key} …", flush=True)
            res = None
            for attempt in (1, 2):
                try:
                    res = one_day(day)
                    break
                except Exception as e:
                    print(f"  tentative {attempt} échouée ({e})", flush=True)
            else:
                print("  journée sautée, sera reprise au prochain lancement")
                day += timedelta(days=1)
                continue
            data[key] = res if res is not None else {}
            n = (len(res) - 1) if res else 0
            print(f"  {'archive absente' if res is None else str(n) + ' vols'}")
            json.dump(data, open(OUT, "w"), sort_keys=True)
        day += timedelta(days=1)
    print(f"Terminé -> {OUT} ({OUT.stat().st_size/1e6:.1f} Mo)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
