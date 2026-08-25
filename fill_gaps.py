#!/usr/bin/env python3
"""
Boucheur de trous : complète les journées vides de ram_flights.json
grâce à l'API historique d'OpenSky Network (compte gratuit requis).

Identifiants attendus en variables d'environnement (GitHub Secrets) :
  OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET
"""
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "ram_flights.json"
FLEET = json.load(open(HERE / "fleet_RAM.json"))
TOKEN_URL = ("https://auth.opensky-network.org/auth/realms/opensky-network/"
             "protocol/openid-connect/token")
API = "https://opensky-network.org/api/flights/aircraft"

GAPS = ["2025-12-25", "2025-12-31", "2026-05-05", "2026-05-06",
        "2026-05-07", "2026-06-11"]


def get_token():
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["OPENSKY_CLIENT_ID"],
        "client_secret": os.environ["OPENSKY_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def flights_of(hexc, begin, end, token):
    url = f"{API}?icao24={hexc.lower()}&begin={begin}&end={end}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (404,):     # aucun vol pour cet avion sur la période
            return []
        if e.code == 429:        # limite de débit : on souffle puis on réessaie
            time.sleep(60)
            return flights_of(hexc, begin, end, token)
        raise


def main():
    data = json.load(open(OUT))
    token = get_token()
    fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")
    for day in GAPS:
        if data.get(day) and data[day].get("_src") == "opensky":
            continue  # déjà bouché
        d0 = int(datetime.fromisoformat(day + "T00:00:00+00:00").timestamp())
        d1 = d0 + 86400
        found = {}
        for hexc, info in FLEET.items():
            for f in flights_of(hexc, d0, d1, token) or []:
                cs = (f.get("callsign") or "").strip()
                if not cs:
                    cs = info[0]  # pas de callsign transmis : immat en clé
                found[cs] = {
                    "reg": info[0], "type": info[1],
                    "from_utc": fmt(f["firstSeen"]), "to_utc": fmt(f["lastSeen"]),
                    "fl_max": None, "gs_max": None, "squawk": None,
                    "dep": None, "arr": None,
                    "dep_apt": f.get("estDepartureAirport"),
                    "arr_apt": f.get("estArrivalAirport"),
                }
            time.sleep(0.4)  # courtoisie envers l'API
        found["_v"] = 4
        found["_src"] = "opensky"
        data[day] = found
        print(f"{day}: {len(found)-2} vols récupérés via OpenSky")
        json.dump(data, open(OUT, "w"), sort_keys=True)
    print("Terminé.")


if __name__ == "__main__":
    main()
