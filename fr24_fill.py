#!/usr/bin/env python3
"""
Enrichissement FR24 : complète ram_flights.json avec l'API officielle
Flightradar24 (Flight summary light), sans écraser les données ADSB.lol
existantes (plus riches : FL, vitesse, squawk).

- bouche les journées vides (les 6) entièrement
- ajoute aux autres journées les vols que les récepteurs communautaires
  ont ratés (Afrique…), marqués "src": "fr24"

Usage : python3 fr24_fill.py 2025-12-25 2025-12-25
Secret attendu : FR24_API_TOKEN (GitHub Secrets)
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "ram_flights.json"
API = "https://fr24api.flightradar24.com/api/flight-summary/light"
TOKEN = os.environ["FR24_API_TOKEN"]
log = lambda *a: print(*a, flush=True)


def call(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "Accept-Version": "v1",
        "User-Agent": "ram-roster-app/1.0",
    })
    for attempt in (1, 2, 3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read()[:200]
            if e.code == 402:
                log("  CREDITS FR24 INSUFFISANTS — arrêt propre, acquis sauvegardé.")
                sys.exit(0)
            if e.code == 429:
                log(f"  429, pause 15 s (essai {attempt}/3)"); time.sleep(15); continue
            log(f"  HTTP {e.code}: {body}"); return None
        except Exception as ex:
            log(f"  erreur réseau ({ex}), essai {attempt}/3"); time.sleep(10)
    return None


def hhmm(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")) \
                       .strftime("%H:%M")
    except ValueError:
        return None


def one_day(day_iso):
    """Retourne {callsign: fiche} pour tous les vols RAM du jour selon FR24."""
    found = {}
    f0 = day_iso + "T00:00:00Z"
    f1 = day_iso + "T23:59:59Z"
    res = call({"operating_as": "RAM",
                "flight_datetime_from": f0, "flight_datetime_to": f1})
    for f in (res or {}).get("data", []):
        cs = (f.get("callsign") or "").strip()
        num = (f.get("flight") or "").strip()          # ex: AT800
        if not cs:
            cs = "RAM" + num[2:] if num.startswith("AT") else (num or "?")
        rec = {
            "reg": f.get("reg") or "?",
            "type": f.get("type") or "?",
            "from_utc": hhmm(f.get("datetime_takeoff")) or "?",
            "to_utc": hhmm(f.get("datetime_landed")) or "?",
            "fl_max": None, "gs_max": None, "squawk": None,
            "dep": None, "arr": None,
            "dep_apt": f.get("orig_icao"), "arr_apt": f.get("dest_icao"),
            "flight_no": num or None,
            "src": "fr24",
        }
        prev = found.get(cs)
        if prev is None or (rec["from_utc"] or "") < (prev["from_utc"] or ""):
            found[cs] = rec
    return found


def main(start, end):
    data = json.load(open(OUT))
    day, end = date.fromisoformat(start), date.fromisoformat(end)
    total_added = 0
    while day <= end:
        key = day.isoformat()
        existing = data.get(key) or {}
        fr24 = one_day(key)
        added = 0
        for cs, rec in fr24.items():
            if cs in existing:      # ADSB.lol déjà là (plus riche) : on garde
                continue
            existing[cs] = rec
            added += 1
        if added or not data.get(key):
            existing["_v"] = 4
            data[key] = existing
            json.dump(data, open(OUT, "w"), sort_keys=True)
        n_day = len([k for k in existing if not k.startswith("_")])
        log(f"{key}: {len(fr24)} vols FR24, {added} ajoutés "
            f"(journée: {n_day} vols au total)")
        total_added += added
        day += timedelta(days=1)
        time.sleep(1)
    log(f"Terminé : {total_added} vols ajoutés au fichier.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
