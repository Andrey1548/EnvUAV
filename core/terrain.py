import requests
from functools import lru_cache

OPENMETEO_URL = "https://api.open-meteo.com/v1/elevation"


@lru_cache(maxsize=200000)
def get_elevation(lat, lon):

    lat = float(lat)
    lon = float(lon)

    try:
        url = f"{OPENMETEO_URL}?latitude={lat}&longitude={lon}"
        r = requests.get(url, timeout=1.5)

        js = r.json()

        elev = js.get("elevation")

        if isinstance(elev, list) and len(elev) > 0:
            return float(elev[0])

        if isinstance(elev, (int, float)):
            return float(elev)

        raise ValueError("Недійсний формат рельєфу Open-Meteo")

    except Exception as e:
        print(f"[DEM] Open-Meteo помилка в {lat},{lon}: {e}")
        return 0.0


def flight_altitude_agl(lat, lon, target_agl=50):
    ground = get_elevation(lat, lon)
    return ground + target_agl
