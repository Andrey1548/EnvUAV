import math
import requests
from core.terrain import get_elevation

def bearing_deg(p1, p2):
    lat1, lon1 = map(math.radians, (p1[0], p1[1]))
    lat2, lon2 = map(math.radians, (p2[0], p2[1]))
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def wind_along_track_kmh(wind_speed_ms, wind_dir_deg, track_deg):
    to_dir = (wind_dir_deg + 180.0) % 360.0
    rel = math.radians((to_dir - track_deg + 540.0) % 360.0 - 180.0)
    v_kmh = wind_speed_ms * 3.6
    return v_kmh * math.cos(rel)


def energy_per_km_wh(speed_kmh, wind_along_kmh=0.0, payload_kg=0.0):
    a, b = 6.0, 0.06
    base = a + b * (speed_kmh ** 2)

    wind_factor = max(0.7, min(1.5, 1.0 + (-wind_along_kmh) / 200.0))
    payload_factor = 1.0 + 0.03 * payload_kg

    return base * wind_factor * payload_factor

def ll_dist_km(p1, p2):
    lat1, lon1 = p1
    lat2, lon2 = p2
    km_per_deg = 111.0

    dx = (lon2 - lon1) * km_per_deg * math.cos(math.radians((lat1 + lat2) / 2.0))
    dy = (lat2 - lat1) * km_per_deg

    return math.hypot(dx, dy)

def leg_energy_wh(p1, p2, speed_kmh, wind_speed_ms, wind_dir_deg, payload_kg=0.0):
    d_km = ll_dist_km(p1, p2)
    if d_km < 1e-9:
        return 0.0

    track = bearing_deg(p1, p2)
    w_along = wind_along_track_kmh(wind_speed_ms, wind_dir_deg, track)

    horizontal_energy = energy_per_km_wh(speed_kmh, w_along, payload_kg) * d_km

    try:
        h1 = get_elevation(p1[0], p1[1])
        h2 = get_elevation(p2[0], p2[1])
    except Exception as e:
        print(f"[DEM] ERROR: {e}")
        return horizontal_energy

    dh = h2 - h1

    CLIMB = 0.12
    DESC  = 0.03

    vertical_energy = dh * CLIMB if dh > 0 else abs(dh) * DESC

    return horizontal_energy + vertical_energy


def leg_energy_wh_cached(p1, p2, h1, h2, speed_kmh, wind_speed_ms, wind_dir_deg, payload_kg=0.0):
    d_km = ll_dist_km(p1, p2)
    if d_km < 1e-6:
        return 0.0

    track = bearing_deg(p1, p2)
    w_along = wind_along_track_kmh(wind_speed_ms, wind_dir_deg, track)
    horizontal_energy = energy_per_km_wh(speed_kmh, w_along, payload_kg) * d_km

    dh = h2 - h1
    vertical_energy = dh * 0.12 if dh > 0 else abs(dh) * 0.03

    return horizontal_energy + vertical_energy

def get_weather(lat, lon):
    try:
        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&units=metric&lang=ua"
            "&appid=d265b3207144c2a738c18e5ed39952d6"
        )

        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            print("[WEATHER] API error:", r.text)
            return None

        data = r.json()
        return {
            "temp": data["main"]["temp"],
            "wind_speed": data["wind"]["speed"],
            "wind_deg": data["wind"].get("deg", 0),
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"],
            "visibility": data.get("visibility", 10000),
        }

    except Exception as e:
        print("[WEATHER] Exception:", e)
        return None
