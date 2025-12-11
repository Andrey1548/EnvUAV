from flask import Blueprint, jsonify, request, make_response
from core.models import Mission, MissionRoute
from shapely.wkb import loads as load_wkb
from core.terrain import flight_altitude_agl
import json

export_bp = Blueprint("export_bp", __name__)

def build_route_with_agl(route_2d, target_agl=50):
    route_3d = []
    for lat, lon in route_2d:
        alt = flight_altitude_agl(lat, lon, target_agl)
        route_3d.append((lat, lon, alt))
    return route_3d


def export_geojson(route):
    return json.dumps({
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [lon, lat, alt] for lat, lon, alt in route
            ],
        },
        "properties": {}
    }, indent=2)


def export_kml(route):
    coords = "\n".join(f"{lon},{lat},{alt}" for lat, lon, alt in route)

    return f"""
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <Placemark>
    <name>UAV Mission Route</name>
    <LineString>
      <altitudeMode>absolute</altitudeMode>
      <coordinates>
        {coords}
      </coordinates>
    </LineString>
  </Placemark>
</Document>
</kml>
"""


def export_csv(route):
    lines = ["lat,lon,alt"]
    for lat, lon, alt in route:
        lines.append(f"{lat},{lon},{alt}")
    return "\n".join(lines)


def export_dji(route):
    waypoints = []
    for idx, (lat, lon, alt) in enumerate(route):
        waypoints.append({
            "waypointIndex": idx,
            "coordinate": {"latitude": lat, "longitude": lon},
            "altitude": alt,
            "gimbalPitch": -90,
            "turnMode": 0,
            "autoFlightSpeed": 5.0,
        })

    return {
        "version": "v2",
        "missionType": "waypoint",
        "waypointPath": waypoints,
    }


def export_qgc(route):
    items = []

    for i, (lat, lon, alt) in enumerate(route):
        items.append({
            "id": i,
            "command": 16,
            "coordinate": [lat, lon, alt],
            "type": "SimpleItem",
            "autoContinue": True
        })

    return {
        "fileType": "Plan",
        "mission": {"items": items}
    }

@export_bp.route("/missions/<int:mid>/export")
def export_mission(mid):
    fmt = request.args.get("fmt", "").lower()

    mission = Mission.query.get(mid)
    if not mission:
        return jsonify({"error": "Mission not found"}), 404

    route_records = MissionRoute.query.filter_by(mission_id=mid).all()
    if not route_records:
        return jsonify({"error": "Mission has no stored route"}), 400

    best_route = max(route_records, key=lambda r: r.length_km or 0)

    geom = load_wkb(bytes(best_route.geom.data))
    coords_2d = [(lat, lon) for lon, lat in geom.coords]

    route_3d = build_route_with_agl(coords_2d, target_agl=50)

    if fmt == "geojson":
        data = export_geojson(route_3d)
        resp = make_response(data)
        resp.headers["Content-Type"] = "application/geo+json"
        return resp

    if fmt == "kml":
        data = export_kml(route_3d)
        resp = make_response(data)
        resp.headers["Content-Type"] = "application/vnd.google-earth.kml+xml"
        return resp

    if fmt == "csv":
        data = export_csv(route_3d)
        return make_response(data)

    if fmt == "dji":
        return make_response(export_dji(route_3d))

    if fmt in ("qgc", "plan"):
        return make_response(json.dumps(export_qgc(route_3d), indent=2))

    return jsonify({"error": "Unknown format"}), 400