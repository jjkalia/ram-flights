#!/usr/bin/env python3
"""
Calcul GRATUIT des distances pour TOUS les vols du fichier :
distance orthodromique (grand cercle) entre aéroports de départ et
d'arrivée — ou entre premiers/derniers points captés pour les vols ADSB.
Répare au passage les valeurs corrompues de l'épisode FR24 (division
par 1000 erronée). Zéro crédit, zéro API : juste des maths.

Usage : python3 distances.py   (aucun argument)
"""
import json, math, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "ram_flights.json"
AIRPORTS_URL = ("https://raw.githubusercontent.com/wiedehopf/tar1090-db/"
                "master/airport-coords.json")


def gc_km(lat1, lon1, lat2, lon2):
    """Distance grand cercle en km."""
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p)
         * (1 - math.cos((lon2 - lon1) * p)) / 2)
    return round(12742 * math.asin(math.sqrt(a)))


def main():
    print("Téléchargement de la table des aéroports…", flush=True)
    raw = json.load(urllib.request.urlopen(AIRPORTS_URL, timeout=60))
    # format: {"GMMN": [lat, lon, ...], ...} — on normalise
    apt = {}
    for k, v in raw.items():
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            apt[k.upper()] = (float(v[0]), float(v[1]))
    print(f"{len(apt)} aéroports chargés.", flush=True)

    data = json.load(open(OUT))
    done = miss = 0
    for day, flights in data.items():
        if not flights:
            continue
        for cs, v in flights.items():
            if cs.startswith("_"):
                continue
            v.pop("dist_km", None)          # purge des valeurs corrompues
            coords = None
            d_apt = (v.get("dep_apt") or "").upper()
            a_apt = (v.get("arr_apt") or "").upper()
            if d_apt in apt and a_apt in apt:
                coords = (*apt[d_apt], *apt[a_apt])
            elif v.get("dep") and v.get("arr"):
                coords = (*v["dep"], *v["arr"])
            if coords:
                v["dist_gc_km"] = gc_km(*coords)
                done += 1
            else:
                v.pop("dist_gc_km", None)
                miss += 1
    json.dump(data, open(OUT, "w"), sort_keys=True)
    total = done + miss
    print(f"Distances calculées : {done}/{total} vols "
          f"({100*done//max(total,1)} %) — {miss} sans coordonnées exploitables.")


if __name__ == "__main__":
    main()
