#!/usr/bin/env python3
"""
Boucheur de trous v2 — complète les journées vides via OpenSky Network.
- 12 requêtes par jour (tranches de 2 h, tous avions) au lieu de 420
- affichage en temps réel de chaque étape
- si OpenSky nous freine trop, abandon propre avec sauvegarde du partiel

Identifiants attendus (GitHub Secrets) :
  OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "ram_flights.json"
FLEET = {k.lower(): v for k, v in json.load(open(HERE / "fleet_RAM.json")).items()}
TOKEN_URL = ("https://auth.opensky-network.org/auth/realms/opensky-network/"
             "protocol/openid-connect/token")
API = "https://opensky-network.org/api/flights/aircraft"
GAPS = ["2025-12-25", "2025-12-31", "2026-05-05", "2026-05-06",
        "2026-05-07", "2026-06-11"]
MAX_RETRY_PER_CALL = 3

log = lambda *a: print(*a, flush=True)


def get_token():
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["OPENSKY_CLIENT_ID"],
        "client_secret": os.environ["OPENSKY_CLIENT_SECRET"],
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data),
                                timeout=30) as r:
        log("[token OpenSky obtenu]")
        return json.load(r)["access_token"]


def call(url, token):
    for attempt in range(1, MAX_RETRY_PER_CALL + 1):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=45) as r:
                remaining = r.headers.get("X-Rate-Limit-Remaining")
                if remaining is not None:
                    log(f"    [crédits OpenSky restants : {remaining}]")
                    if remaining.isdigit() and int(remaining) < 100:
                        log("    Presque à sec : arrêt propre pour garder une "
                            "marge. Relancez demain, le script reprendra seul.")
                        result = json.load(r)
                        return ("LOW_CREDITS", result)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []          # aucun vol sur la tranche
            wait = int(e.headers.get("X-Rate-Limit-Retry-After-Seconds", 30)) \
                   if e.code == 429 else 10
            if wait > 300:         # quota JOURNALIER épuisé : inutile d'insister
                log(f"    HTTP 429 : quota quotidien OpenSky épuisé "
                    f"(réinitialisation dans ~{wait//3600}h). "
                    f"Relancez le workflow demain — il reprendra tout seul.")
                sys.exit(0)
            log(f"    HTTP {e.code} (essai {attempt}/{MAX_RETRY_PER_CALL}), "
                f"attente {wait}s")
            if attempt == MAX_RETRY_PER_CALL:
                return None        # on renonce à cette tranche
            time.sleep(wait)
        except Exception as ex:
            log(f"    erreur réseau ({ex}), essai {attempt}/{MAX_RETRY_PER_CALL}")
            if attempt == MAX_RETRY_PER_CALL:
                return None
            time.sleep(10)


def main():
    data = json.load(open(OUT))
    token = get_token()
    fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M")
    gave_up = 0
    for day in GAPS:
        if data.get(day) and data[day].get("_src") == "opensky":
            log(f"{day}: déjà bouché, on saute")
            continue
        log(f"{day}: interrogation avion par avion ({len(FLEET)} appareils)…")
        d0 = int(datetime.fromisoformat(day + "T00:00:00+00:00").timestamp())
        d1 = d0 + 86400
        found = {}
        hard_429 = 0
        for i, (hexc, info) in enumerate(sorted(FLEET.items()), 1):
            res = call(f"{API}?icao24={hexc}&begin={d0}&end={d1}", token)
            low_credits = isinstance(res, tuple) and res[0] == "LOW_CREDITS"
            if low_credits:
                res = res[1]
            if res is None:
                gave_up += 1
                hard_429 += 1
                if hard_429 >= 3 and not found:
                    log("  DIAGNOSTIC : cet endpoint semble lui aussi restreint "
                        "pour les comptes Standard. Arrêt propre — il faudra "
                        "une autre voie (accès Trino ou saisie manuelle).")
                    sys.exit(0)
                continue
            for f in res:
                cs = (f.get("callsign") or "").strip() or info[0]
                rec = {
                    "reg": info[0], "type": info[1],
                    "from_utc": fmt(f["firstSeen"]), "to_utc": fmt(f["lastSeen"]),
                    "fl_max": None, "gs_max": None, "squawk": None,
                    "dep": None, "arr": None,
                    "dep_apt": f.get("estDepartureAirport"),
                    "arr_apt": f.get("estArrivalAirport"),
                }
                prev = found.get(cs)
                if prev is None or rec["from_utc"] < prev["from_utc"]:
                    found[cs] = rec
            if res:
                log(f"  [{i}/{len(FLEET)}] {info[0]} : {len(res)} vol(s)")
            if low_credits:
                found["_v"] = 4
                json.dump(data | {day: found}, open(OUT, "w"), sort_keys=True)
                sys.exit(0)
            time.sleep(0.5)
        found["_v"] = 4
        found["_src"] = "opensky"
        data[day] = found
        json.dump(data, open(OUT, "w"), sort_keys=True)
        log(f"{day}: TOTAL {len(found)-2} vols RAM récupérés, sauvegardé")
    log(f"Terminé ({gave_up} tranches abandonnées sur l'ensemble).")
    sys.exit(0)


if __name__ == "__main__":
    main()
