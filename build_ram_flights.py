#!/usr/bin/env python3
"""
Construit ram_flights.json : tous les vols RAM (callsign -> immatriculation)
sur une plage de dates, depuis les archives ouvertes ADSB.lol (licence ODbL).

    python build_ram_flights.py 2025-08-01 2026-07-31

- Reprend là où il s'est arrêté si on le relance (les journées déjà
  faites sont sautées) -> on peut l'interrompre sans rien perdre.
- Nécessite fleet_RAM.json (hex -> [immat, type]) dans le même dossier.
- Résultat : ram_flights.json  { "2025-12-08": { "RAM800F": {...} } }
"""
import gzip, io, json, sys, tarfile, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "ram_flights.json"
FLEET = {k.lower(): v for k, v in json.load(open(HERE / "fleet_RAM.json")).items()}
WANTED = {f"./traces/{h[-2:]}/trace_full_{h}.json" for h in FLEET}

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
        return None  # archive absente pour ce jour
    for m in tar:
        if m.name not in remaining:
            continue
        remaining.discard(m.name)
        raw = tar.extractfile(m).read()
        try: d = json.loads(gzip.decompress(raw))
        except gzip.BadGzipFile: d = json.loads(raw)
        base, reg, typ = d.get("timestamp", 0), d.get("r", "?"), d.get("t", "?")
        seen = {}
        for p in d.get("trace", []):
            if len(p) > 8 and isinstance(p[8], dict) and p[8].get("flight"):
                cs = p[8]["flight"].strip()
                if not cs.startswith("RAM"):
                    continue
                ts = base + p[0]
                lo, hi = seen.get(cs, (ts, ts))
                seen[cs] = (min(lo, ts), max(hi, ts))
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")
        for cs, (lo, hi) in seen.items():
            flights[cs] = {"reg": reg, "type": typ,
                           "from_utc": fmt(lo), "to_utc": fmt(hi)}
        if not remaining:
            break  # toute la flotte trouvée, inutile de lire la suite
    return flights


def main(start, end):
    data = json.load(open(OUT)) if OUT.exists() else {}
    day, end = date.fromisoformat(start), date.fromisoformat(end)
    while day <= end:
        key = day.isoformat()
        if key not in data:
            print(f"{key} …", flush=True)
            res = one_day(day)
            data[key] = res if res is not None else {}
            if res is None:
                print(f"  (archive absente)")
            else:
                print(f"  {len(res)} vols")
            json.dump(data, open(OUT, "w"), sort_keys=True)  # sauvegarde continue
        day += timedelta(days=1)
    print(f"Terminé -> {OUT} ({OUT.stat().st_size/1e6:.1f} Mo)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
