from __future__ import annotations
import math
import uuid
from typing import List, Tuple, Dict
import networkx as nx
import pyproj
from flask_socketio import emit
from shapely.geometry import (
    Polygon, LineString, MultiPolygon, MultiLineString, GeometryCollection
)
from shapely.ops import transform
from shapely.affinity import rotate
from core.terrain import flight_altitude_agl, get_elevation
from core.extensions import socketio, db
from core.models import Mission, MissionRoute
from core.utils import get_weather, leg_energy_wh, ll_dist_km, leg_energy_wh_cached
from core.discretization import discretize_area
from core.aco import aco_orienteering

GLOBAL_WIND_SPEED = 0.0
GLOBAL_WIND_DEG = 0.0
GLOBAL_WEATHER_VERSION = 0

CURRENT_JOB_ID: str | None = None
last_route_data: dict = {}

proj_fwd = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
proj_inv = pyproj.Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)

SAFE_AGL = 10.0

def extract_lines(geom) -> List[LineString]:
    if geom is None or geom.is_empty:
        return []

    if isinstance(geom, LineString):
        return [geom]

    if isinstance(geom, MultiLineString):
        return list(geom.geoms)

    if isinstance(geom, GeometryCollection):
        out: List[LineString] = []
        for g in geom.geoms:
            out.extend(extract_lines(g))
        return out

    return []


def build_lawnmower_path_for_cell_metric(
    cell_poly_ll: Polygon,
    orientation_deg: float,
    W_m: float,
    delta_perp_m: float,
    delta_par_m: float,
) -> List[Tuple[float, float]]:
    if cell_poly_ll is None or cell_poly_ll.is_empty:
        return []

    poly_m = transform(lambda x, y: proj_fwd.transform(x, y), cell_poly_ll)
    if poly_m.is_empty:
        return []

    phi = float(orientation_deg)

    poly_rot = rotate(poly_m, angle=-phi, origin="centroid", use_radians=False)
    minx, miny, maxx, maxy = poly_rot.bounds
    height = maxy - miny
    if height < 1.0:
        return []

    lane_step = max(delta_perp_m, 1.0)
    n_lanes = max(2, int(height / lane_step) + 1)

    stripes = []
    for i in range(n_lanes):
        y = miny + i * lane_step
        stripes.append(LineString([
            (minx - 3 * W_m, y),
            (maxx + 3 * W_m, y),
        ]))

    segs: List[LineString] = []
    for ln in stripes:
        inter = poly_rot.intersection(ln)
        if inter.is_empty:
            continue
        segs.extend(extract_lines(inter))

    if not segs:
        return []

    result_xy = []
    flip = False
    segs_sorted = sorted(segs, key=lambda s: s.centroid.y)
    for seg in segs_sorted:
        pts = list(seg.coords)
        if flip:
            pts.reverse()
        result_xy.extend(pts)
        flip = not flip

    if not result_xy:
        return []

    ml = MultiLineString([LineString(result_xy)])
    ml_back = rotate(ml, angle=phi, origin="centroid", use_radians=False)

    result_ll: List[Tuple[float, float]] = []
    for line in extract_lines(ml_back):
        for x, y in line.coords:
            lon, lat = proj_inv.transform(x, y)
            result_ll.append((lat, lon))

    return result_ll

def stitch_cell_paths(
    cells: List[Dict],
    order: List[int],
    base: Tuple[float, float],
    reserve_km: float = 0.5,
    battery_km: float = 5.0,
) -> List[Tuple[float, float]]:
    mission: List[Tuple[float, float]] = []
    remain = battery_km
    pos = base

    def add_points(pts: List[Tuple[float, float]]):
        nonlocal mission, pos, remain
        if not pts:
            return
        mission.extend(pts)
        pos = pts[-1]

    for ci in order:
        if ci < 0 or ci >= len(cells):
            continue
        cell = cells[ci]
        cell_path = cell.get("path", [])
        if not cell_path:
            continue

        direct = cell_path
        rev = list(reversed(cell_path))
        path = direct if ll_dist_km(pos, direct[0]) < ll_dist_km(pos, rev[0]) else rev

        need = ll_dist_km(pos, path[0]) + sum(
            ll_dist_km(a, b) for a, b in zip(path[:-1], path[1:])
        )

        if remain < need + max(reserve_km, ll_dist_km(path[-1], base)):
            if ll_dist_km(pos, base) > 1e-6:
                add_points([pos, base])
            remain = battery_km
            pos = base

        if ll_dist_km(pos, path[0]) > 1e-6:
            add_points([pos, path[0]])

        add_points(path)
        remain -= need

    if ll_dist_km(pos, base) > 1e-6:
        add_points([pos, base])

    return mission

@socketio.on("start_planning")
def handle_start(data):
    from shapely.geometry import Polygon, LineString, MultiLineString
    import math, uuid

    global CURRENT_JOB_ID, last_route_data

    print("\n==============================")
    print("ПОЧАТОК ПЛАНУВАННЯ з ACO")
    print("==============================")

    base = (float(data["lat"]), float(data["lon"]))

    drone = data.get("drone", {})
    battery_wh = float(drone.get("battery_wh", 222.0))
    reserve_pct = float(drone.get("reserve_pct", 20.0))
    speed_kmh = float(drone.get("speed_kmh", drone.get("speed", 40.0)))
    payload_kg = float(drone.get("payload_kg", 1.5))

    h = float(drone.get("altitude", 100.0))
    theta_deg = float(drone.get("fov_deg", 60.0))
    o_perp = float(drone.get("overlap_perp", 0.2))
    o_par = float(drone.get("overlap_par", 0.2))
    grid_type = str(data.get("grid_type", "SQUARE")).upper()
    cell_km = float(data.get("cell", 0.5))

    theta_rad = math.radians(theta_deg)
    W_m = 2.0 * h * math.tan(theta_rad / 2.0)
    delta_perp_m = W_m * (1.0 - o_perp)
    delta_par_m = W_m * (1.0 - o_par)

    weather = get_weather(base[0], base[1]) or {}
    emit("weather_update", weather)

    wind_speed = float(weather.get("wind_speed", 0.0))
    wind_deg = float(weather.get("wind_deg", 0.0))

    usable_energy_wh = battery_wh * max(0.0, (100.0 - reserve_pct)) / 100.0

    nofly_coords = data.get("nofly", [])
    nofly_polys = [Polygon([(lng, lat) for lat, lng in poly]) for poly in nofly_coords]

    job_id = str(uuid.uuid4())
    CURRENT_JOB_ID = job_id
    print(f"Нове ACO завдання: {job_id}")

    area_polygon = None
    cells = []
    graph_edges = []

    if data.get("area_poly"):
        coords = data["area_poly"]
        area_polygon = Polygon([(lng, lat) for lat, lng in coords])

        cells_geo, centroids_geo, G, phi_map = discretize_area(
            area_polygon,
            nofly_polys,
            h=h,
            theta_deg=theta_deg,
            o_perp=o_perp,
            o_par=o_par,
            gridType=grid_type,
            tauMinArea=float(drone.get("min_cell_area", 200.0)),
            cell_size_km=cell_km,
        )

        print(f"[discretize_area] Клітини={len(cells_geo)} Сітка={grid_type} Клітина≈{cell_km}км")

        for idx, c in enumerate(cells_geo):
            if isinstance(c, MultiPolygon):
                c = max(c.geoms, key=lambda g: g.area)

            lat_c, lon_c = c.centroid.y, c.centroid.x
            min_lon, min_lat, max_lon, max_lat = c.bounds
            bbox = (min_lat, min_lon, max_lat, max_lon)
            phi = float(phi_map.get(idx, 0.0))

            path_ll = build_lawnmower_path_for_cell_metric(
                cell_poly_ll=c,
                orientation_deg=phi,
                W_m=W_m,
                delta_perp_m=delta_perp_m,
                delta_par_m=delta_par_m,
            )

            cells.append({
                "idx": idx,
                "geom": c,
                "bbox": bbox,
                "center": (lat_c, lon_c),
                "orientation": phi,
                "path": path_ll or [],
                "weight": 1.0
            })

        # Граф суміжності
        for a, b, d in G.edges(data=True):
            node_a = G.nodes[a]
            node_b = G.nodes[b]
            graph_edges.append({
                "from": (node_a["centroid_lat"], node_a["centroid_lon"]),
                "to": (node_b["centroid_lat"], node_b["centroid_lon"]),
                "weight": float(d.get("weight", 0.0)),
            })

    emit("planner_update", {
        "event": "grid",
        "cells": [{
            "idx": c["idx"],
            "center": c["center"],
            "bbox": c["bbox"],
            "path": c["path"],
            "orientation": c["orientation"],
        } for c in cells],
        "graph_edges": graph_edges
    })

    if not cells:
        emit("planner_update", {
            "event": "aco_done",
            "message": "Не вдалося дискретизувати область"
        })
        return

    points = [base] + [c["center"] for c in cells]
    weights = [0.0] + [c["weight"] for c in cells]
    base_idx = 0

    print(f"[DEM] Вибірка висот для {len(points)} точок ACO...")
    heights = []
    for (lat, lon) in points:
        h_pt = get_elevation(lat, lon)
        heights.append(h_pt)
    print("[DEM] Готово!")

    def energy_fn(i, j):
        return leg_energy_wh_cached(
            points[i], points[j],
            heights[i], heights[j],
            speed_kmh, wind_speed, wind_deg,
            payload_kg
        )

    def energy_back_fn(i):
        return leg_energy_wh_cached(
            points[i], points[base_idx],
            heights[i], heights[base_idx],
            speed_kmh, wind_speed, wind_deg,
            payload_kg
        )

    try:
        order, best_score, best_cost = aco_orienteering(
            points,
            weights,
            base_idx=base_idx,
            energy_fn=energy_fn,
            energy_back_fn=energy_back_fn,
            energy_budget_wh=usable_energy_wh,
            reserve_wh=usable_energy_wh * 0.1,
            ants=int(data.get("ants", 20)),
            iterations=int(data.get("iters", 10)),
            nofly=nofly_polys,
            job_id=job_id,
            clip_polygon=area_polygon,
        )
    except Exception as e:
        print(f"ACO ERROR: {e}")
        emit("planner_update", {"event": "aco_error", "message": str(e)})
        return

    if not order:
        emit("planner_update", {"event": "aco_done", "message": "Маршрут не знайдено"})
        return

    visit_cells = [i - 1 for i in order[1:-1] if i > 0]

    logical_route = [base]
    for ci in visit_cells:
        logical_route.append(cells[ci]["center"])
    logical_route.append(base)

    print(f"[Logical] raw points = {len(logical_route)}")

    if area_polygon is not None:
        line = LineString([(lon, lat) for lat, lon in logical_route])
        clipped = line.intersection(area_polygon)

        def to_ll(g):
            if isinstance(g, LineString):
                return [(lat, lon) for lon, lat in g.coords]
            if isinstance(g, MultiLineString):
                pts = []
                for seg in g.geoms:
                    pts.extend([(lat, lon) for lon, lat in seg.coords])
                return pts
            return []

        clipped_route = to_ll(clipped)
        if clipped_route:
            logical_route = clipped_route
        else:
            print("Логічний маршрут обрізано до порожнього — використовуємо необроблений маршрут")

    logical_km = 0.0
    if len(logical_route) > 1:
        logical_km = sum(
            ll_dist_km(a, b)
            for a, b in zip(logical_route[:-1], logical_route[1:])
        )

    approx_km_per_wh = 0.015
    battery_km = usable_energy_wh * approx_km_per_wh
    reserve_km = battery_km * 0.1

    coverage_route = stitch_cell_paths(
        cells,
        visit_cells,
        base,
        reserve_km=reserve_km,
        battery_km=battery_km,
    )

    coverage_km = 0.0
    if len(coverage_route) > 1:
        coverage_km = sum(
            ll_dist_km(a, b)
            for a, b in zip(coverage_route[:-1], coverage_route[1:])
        )

    adaptive_route = [(lat, lon, h) for lat, lon in coverage_route]

    last_route_data = {
        "logical": logical_route,
        "coverage": adaptive_route,
        "total_km": round(coverage_km, 3),
        "energy_wh": best_cost
    }

    emit("planner_update", {
        "event": "done",
        "route": logical_route,
        "mission_len_km": round(logical_km, 3),
        "graph_edges": graph_edges
    })

    print("==== Фінальний маршрут ====")
    print("Довжина:", round(logical_km, 3), "км")
    print("Енергія:", best_cost, "Вт·год")
    print("================\n")

@socketio.on("get_weather")
def handle_weather(data):
    lat = float(data["lat"])
    lon = float(data["lon"])
    w = get_weather(lat, lon)
    if not w:
        emit("weather_error", {"msg": "Не вдалося отримати погоду"})
    else:
        emit("weather_update", w)


@socketio.on("update_nofly")
def handle_update_nofly(data):
    global CURRENT_JOB_ID
    print("Оновлено no-fly зони, перезапуск маршруту...")
    CURRENT_JOB_ID = None
    socketio.sleep(0.1)
    handle_start(data)

@socketio.on("weather_update_backend")
def handle_dynamic_weather(w):
    global GLOBAL_WIND_SPEED, GLOBAL_WIND_DEG, GLOBAL_WEATHER_VERSION

    if not w:
        return

    GLOBAL_WIND_SPEED = float(w.get("wind_speed", 0))
    GLOBAL_WIND_DEG = float(w.get("wind_deg", 0))

    GLOBAL_WEATHER_VERSION += 1

    print(f"Погоду змінено → вітер={GLOBAL_WIND_SPEED} m/s Напрямок={GLOBAL_WIND_DEG}")

    emit("planner_update", {
        "event": "weather_dynamic",
        "wind_speed": GLOBAL_WIND_SPEED,
        "wind_deg": GLOBAL_WIND_DEG
    })