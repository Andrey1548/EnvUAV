from flask import Blueprint, request, jsonify
from core.extensions import db, socketio
from core.models import Mission, MissionArea, MissionNoFly, MissionRoute
from core.mission_logic import handle_start, get_weather, last_route_data
from shapely.geometry import Polygon
from shapely import wkb
from geoalchemy2.shape import from_shape

mission_bp = Blueprint("mission_routes", __name__)

@mission_bp.route("/missions/save", methods=["POST"])
def save_mission():
    from shapely.geometry import Polygon, LineString
    from shapely import wkb
    from geoalchemy2.shape import from_shape
    from core.mission_logic import last_route_data

    data = request.json
    mission_id = data.get("mission_id")

    try:
        if mission_id:
            mission = db.session.get(Mission, int(mission_id))
            if not mission:
                raise Exception(f"Місію з ID={mission_id} не знайдено")
        else:
            mission = Mission(
                name=data.get("name", f"Mission_{int(__import__('time').time())}"),
                description=data.get("description", ""),
                battery_wh=data.get("drone", {}).get("battery_wh", 0),
                reserve_pct=data.get("drone", {}).get("reserve_pct", 0),
                speed_kmh=data.get("drone", {}).get("speed_kmh", 0),
                payload_kg=data.get("drone", {}).get("payload_kg", 0)
            )
            db.session.add(mission)
            db.session.flush()

        if "area_poly" in data and data["area_poly"]:
            poly = Polygon([(lng, lat) for lat, lng in data["area_poly"]])
            db.session.add(MissionArea(
                mission_id=mission.id,
                geom=from_shape(poly, srid=4326)
            ))

        for poly_coords in data.get("nofly", []):
            poly = Polygon([(lng, lat) for lat, lng in poly_coords])
            db.session.add(MissionNoFly(
                mission_id=mission.id,
                geom=from_shape(poly, srid=4326),
                source="user"
            ))

        if last_route_data and "logical" in last_route_data:
            route_3d = last_route_data["logical"]

            route_points = [(lat, lon) for (lat, lon, *_ ) in route_3d]

            total_km = last_route_data["total_km"]
            energy_wh = last_route_data["energy_wh"]

            line = LineString([(lon, lat) for lat, lon in route_points])
            geom = from_shape(line, srid=4326)

            db.session.add(MissionRoute(
                mission_id=mission.id,
                geom=geom,
                length_km=round(total_km, 3),
                energy_wh=energy_wh
            ))
            print(f"Маршрут додано до місії #{mission.id}")

            print("3D маршрут збережено!")
        else:
            print("Немає маршруту для збереження.")

        db.session.commit()
        return jsonify({"status": "ok", "mission_id": mission.id})

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500


@mission_bp.route("/missions/list", methods=["GET"])
def list_missions():
    missions = Mission.query.order_by(Mission.created_at.desc()).all()
    data = [{
        "id": m.id,
        "name": m.name,
        "created_at": m.created_at,
        "battery_wh": m.battery_wh,
        "speed_kmh": m.speed_kmh
    } for m in missions]
    return jsonify(data)

def flatten_route(route):
    if isinstance(route, list) and len(route) == 1 and isinstance(route[0], list):
        return route[0]
    return route

@mission_bp.route("/missions/<int:mission_id>")
def get_mission(mission_id):

    def geom_to_coords(geom):
        if geom is None:
            return []

        try:
            if hasattr(geom, "data"):
                shape = wkb.loads(bytes(geom.data))
            else:
                shape = wkb.loads(bytes(geom))
        except Exception as e:
            print("Помилка WKB:", e)
            return []

        def convert_point(pt):
            if len(pt) == 3:
                lon, lat, alt = pt
                return (lat, lon, alt)
            else:
                lon, lat = pt
                return (lat, lon)

        if shape.geom_type == "Polygon":
            return [[convert_point(pt) for pt in shape.exterior.coords]]

        if shape.geom_type == "MultiPolygon":
            res = []
            for part in shape.geoms:
                res.append([convert_point(pt) for pt in part.exterior.coords])
            return res

        if shape.geom_type == "LineString":
            return [convert_point(pt) for pt in shape.coords]

        if shape.geom_type == "MultiLineString":
            pts = []
            for part in shape.geoms:
                pts.extend(convert_point(pt) for pt in part.coords)
            return pts

        return []

    mission = db.session.get(Mission, mission_id)
    if mission is None:
        return jsonify({"error": "Mission not found"}), 404

    areas = MissionArea.query.filter_by(mission_id=mission_id).all()
    nofly = MissionNoFly.query.filter_by(mission_id=mission_id).all()
    routes = MissionRoute.query.filter_by(mission_id=mission_id).all()
    route_points = []
    if routes:
        route_points = geom_to_coords(routes[0].geom)

        if isinstance(route_points, list) and len(route_points) == 1 and isinstance(route_points[0], list):
            route_points = route_points[0]

    data = {
        "id": mission.id,
        "name": mission.name,
        "drone": {
            "battery_wh": mission.battery_wh,
            "reserve_pct": mission.reserve_pct,
            "speed_kmh": mission.speed_kmh,
            "payload_kg": mission.payload_kg
        },

        "areas": [geom_to_coords(a.geom) for a in areas],
        "nofly": [geom_to_coords(n.geom) for n in nofly],
        "route": route_points
    }

    print(f"Завантажено місію #{mission_id}: route pts = {len(route_points)}")

    return jsonify(data)

@mission_bp.route("/nofly/real")
def get_real_nofly():
    from core.nofly import load_real_nofly_zones
    from flask import request, jsonify

    min_lat = float(request.args.get("min_lat", 48.0))
    max_lat = float(request.args.get("max_lat", 52.0))
    min_lon = float(request.args.get("min_lon", 29.0))
    max_lon = float(request.args.get("max_lon", 33.0))

    padding = 2.0
    min_lat -= padding
    max_lat += padding
    min_lon -= padding
    max_lon += padding

    zones = load_real_nofly_zones((min_lon, min_lat, max_lon, max_lat))
    return jsonify(zones)

@mission_bp.route("/missions/clear", methods=["POST"])
def clear_missions():
    try:
        MissionRoute.query.delete()
        MissionNoFly.query.delete()
        MissionArea.query.delete()
        Mission.query.delete()
        db.session.commit()
        print("Усі дані місій очищено")
        return jsonify({"status": "ok"})
    except Exception as e:
        db.session.rollback()
        print("Помилка очищення БД:", e)
        return jsonify({"status": "error", "message": str(e)}), 500