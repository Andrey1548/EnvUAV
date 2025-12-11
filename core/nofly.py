import requests

OPENAIP_API_KEY = "d9bda2b59d7bd9abebbcf4496492d79f"

def load_real_nofly_zones(bbox=None):
    try:
        url = "https://api.core.openaip.net/api/airspaces"
        headers = {
            "Accept": "application/json",
            "x-openaip-api-key": OPENAIP_API_KEY
        }
        params = {"limit": 200, "type": "1,2,3"}
        if bbox:
            params["bbox"] = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

        print(f"Отримую no-fly зони з OpenAIP для {bbox} ...")
        r = requests.get(url, headers=headers, params=params, timeout=15)

        if r.status_code != 200:
            print(f"Помилка OpenAIP: {r.status_code} — {r.text[:200]}")
            return []

        data = r.json()
        zones = []
        for z in data.get("items", []):
            geom = z.get("geometry")
            if not geom:
                continue
            if geom["type"] == "Polygon":
                coords = geom["coordinates"][0]
                zones.append([(lat, lon) for lon, lat in coords])
            elif geom["type"] == "MultiPolygon":
                for part in geom["coordinates"]:
                    coords = part[0]
                    zones.append([(lat, lon) for lon, lat in coords])

        print(f"Завантажено {len(zones)} зон з OpenAIP")
        return zones

    except Exception as e:
        print(f"Помилка при завантаженні зон: {e}")
        return []
