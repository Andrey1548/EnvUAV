import requests
from flask import Blueprint, request, jsonify

forest_bp = Blueprint("forest_bp", __name__)

@forest_bp.route("/forest")
def forest_area():
    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))

    query = f"""
    [out:json];
    (
      way["landuse"="forest"](around:300,{lat},{lon});
      way["natural"="wood"](around:300,{lat},{lon});
      way["natural"="forest"](around:300,{lat},{lon});
    );
    (._;>;);
    out geom;
    """

    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": query})

    if r.status_code != 200:
        return jsonify({"polygons": []})

    data = r.json()
    polygons = []

    for el in data.get("elements", []):
        if "geometry" in el:
            poly = [(p["lat"], p["lon"]) for p in el["geometry"]]
            polygons.append(poly)

    return jsonify({"polygons": polygons})

@forest_bp.route("/forest/bbox")
def forest_bbox():
    lat = float(request.args["lat"])
    lon = float(request.args["lon"])

    delta = 0.004
    min_lat = lat - delta
    max_lat = lat + delta
    min_lon = lon - delta
    max_lon = lon + delta

    query = f"""
    [out:json][timeout:25];
    (
      way["landuse"="forest"]({min_lat},{min_lon},{max_lat},{max_lon});
      way["natural"="wood"]({min_lat},{min_lon},{max_lat},{max_lon});
      relation["landuse"="forest"]({min_lat},{min_lon},{max_lat},{max_lon});
      relation["natural"="wood"]({min_lat},{min_lon},{max_lat},{max_lon});
    );
    (._;>;);
    out body;
    """

    url = "https://overpass-api.de/api/interpreter"

    try:
        resp = requests.post(url, data=query.encode("utf-8"),
                             headers={"Content-Type": "text/plain"})

        if not resp.text.startswith("{"):
            print("Overpass повернув відповідь не у форматі JSON:")
            print(resp.text[:300])
            return jsonify({"polygons": [], "error": "Overpass повернув HTML-код або помилку"}), 500

        data = resp.json()

    except Exception as e:
        print("Overpass помилка:", e)
        return jsonify({"polygons": [], "error": str(e)}), 500

    nodes = {
        n["id"]: (n["lat"], n["lon"])
        for n in data["elements"] if n["type"] == "node"
    }

    polys = []
    for el in data["elements"]:
        if el["type"] == "way" and "nodes" in el:
            coords = [nodes[nid] for nid in el["nodes"] if nid in nodes]
            if len(coords) > 2:
                polys.append(coords)

    return jsonify({"polygons": polys})