import math
from typing import List, Tuple, Dict, Optional

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, LineString, box
from shapely.ops import transform, unary_union
import pyproj
import networkx as nx

LatLon = Tuple[float, float]
CellPoly = Polygon

def project_to_metric_latlon(geom):
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)

    def _func(lat, lon):
        X, Y = transformer.transform(lon, lat)
        return X, Y

    return transform(_func, geom)


def project_to_geo_latlon(geom):
    transformer = pyproj.Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)

    def _func(X, Y):
        lon, lat = transformer.transform(X, Y)
        return lat, lon

    return transform(_func, geom)

def compute_sensor_footprint(
    h: float,
    theta_deg: float,
    o_perp: float,
    o_par: float,
    cell_size_km: Optional[float] = None
) -> Tuple[float, float, float, float]:
    theta_rad = math.radians(theta_deg)
    W = 2.0 * h * math.tan(theta_rad / 2.0)

    if cell_size_km is None or cell_size_km <= 0:
        DeltaPerp = W * (1.0 - o_perp)
    else:
        DeltaPerp = cell_size_km * 1000.0

    DeltaPar = W * (1.0 - o_par)
    buffer = 0.5 * W * o_perp

    return W, DeltaPerp, DeltaPar, buffer

def regular_grid_centers(bbox_metric: Tuple[float, float, float, float],
                         dx: float,
                         dy: float) -> List[Tuple[float, float]]:
    minx, miny, maxx, maxy = bbox_metric
    xs = np.arange(minx, maxx + 0.5 * dx, dx)
    ys = np.arange(miny, maxy + 0.5 * dy, dy)
    centers = []
    for x in xs:
        for y in ys:
            centers.append((x, y))
    return centers


def hex_grid_centers(bbox_metric: Tuple[float, float, float, float],
                     pitch: float) -> List[Tuple[float, float]]:
    minx, miny, maxx, maxy = bbox_metric

    dx = pitch
    dy = math.sqrt(3.0) * pitch / 2.0

    centers = []
    y = miny
    row = 0
    while y <= maxx + dy:
        x_offset = 0.0 if row % 2 == 0 else dx / 2.0
        x = minx + x_offset
        while x <= maxx + dx:
            centers.append((x, y))
            x += dx
        y += dy
        row += 1
    return centers

def square_cell(center_xy: Tuple[float, float], side: float) -> Polygon:
    cx, cy = center_xy
    half = side / 2.0
    return box(cx - half, cy - half, cx + half, cy + half)


def hex_cell(center_xy: Tuple[float, float], pitch: float) -> Polygon:
    cx, cy = center_xy
    r = pitch / 2.0
    coords = []
    for k in range(6):
        angle = math.radians(60.0 * k + 30.0)
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        coords.append((x, y))
    return Polygon(coords)

def boustrophedon_decompose(area_m: Polygon,
                            obstacles_m: List[Polygon],
                            sweep_angle_deg: float = 0.0) -> List[Polygon]:
    if isinstance(area_m, MultiPolygon):
        area_m = max(area_m.geoms, key=lambda g: g.area)

    free_space = area_m
    if obstacles_m:
        free_space = area_m.difference(unary_union(obstacles_m))

    if free_space.is_empty:
        return []

    minx, miny, maxx, maxy = free_space.bounds
    span_x = maxx - minx
    span_y = maxy - miny
    approx = max(span_x, span_y)
    n_strips = max(4, int(approx / (min(span_x, span_y) + 1e-6)) * 4)

    angle_rad = math.radians(sweep_angle_deg)
    dx = math.cos(angle_rad)
    dy = math.sin(angle_rad)

    length = math.hypot(span_x, span_y) * 2.0
    subareas: List[Polygon] = []

    for i in range(n_strips):
        t = i / max(1, (n_strips - 1))
        ox = minx + t * span_x
        oy = miny

        p1 = (ox - dx * length, oy - dy * length)
        p2 = (ox + dx * length, oy + dy * length)

        strip = LineString([p1, p2]).buffer(approx / n_strips)
        piece = free_space.intersection(strip)
        if piece.is_empty:
            continue

        if isinstance(piece, MultiPolygon):
            subareas.extend(list(piece.geoms))
        elif isinstance(piece, Polygon):
            subareas.append(piece)

    if not subareas:
        return [free_space]

    return subareas


def assign_orientation_to_cells(cells_m: List[Polygon],
                                subareas: List[Polygon]) -> Dict[int, float]:
    phi_map: Dict[int, float] = {}
    for idx, cell in enumerate(cells_m):
        if cell.is_empty:
            phi_map[idx] = 0.0
            continue

        best_area = 0.0
        for s in subareas:
            inter = cell.intersection(s)
            a = inter.area
            if a > best_area:
                best_area = a

        minx, miny, maxx, maxy = cell.bounds
        dx = maxx - minx
        dy = maxy - miny
        phi = 0.0 if dx >= dy else 90.0
        phi_map[idx] = phi

    return phi_map

def build_adjacency_graph(cells_m: List[Polygon],
                          centroids_m: List[Tuple[float, float]],
                          phi_map: Dict[int, float]) -> nx.Graph:
    G = nx.Graph()
    n = len(cells_m)

    for idx, (cx, cy) in enumerate(centroids_m):
        G.add_node(idx, centroid_x=cx, centroid_y=cy)

    if n <= 1:
        return G

    lambda_turn_km = 0.05

    for i in range(n):
        ci = cells_m[i]
        for j in range(i + 1, n):
            cj = cells_m[j]

            if not (ci.touches(cj) or ci.intersects(cj)):
                continue

            xi, yi = centroids_m[i]
            xj, yj = centroids_m[j]
            dx = xj - xi
            dy = yj - yi
            dist_km = math.hypot(dx, dy) / 1000.0

            phi_i = float(phi_map.get(i, 0.0))
            phi_j = float(phi_map.get(j, 0.0))
            dphi = abs(phi_i - phi_j) % 180.0
            if dphi > 90.0:
                dphi = 180.0 - dphi

            turn_pen_km = lambda_turn_km * (dphi / 90.0)
            weight = dist_km + turn_pen_km

            G.add_edge(i, j,
                       weight=weight,
                       dist_km=dist_km,
                       turn_deg=dphi)

    return G

def discretize_area(
    A_geo: Polygon,
    Obstacles_geo: List[Polygon],
    h: float,
    theta_deg: float,
    o_perp: float,
    o_par: float,
    gridType: str = "SQUARE",
    tauMinArea: float = 200.0,
    cell_size_km: Optional[float] = None,
    priorityMap=None
):
    gridType = str(gridType).upper()

    A_m = project_to_metric_latlon(A_geo)
    Obstacles_m = [project_to_metric_latlon(o) for o in Obstacles_geo]

    W, DeltaPerp, DeltaPar, buffer = compute_sensor_footprint(
        h=h,
        theta_deg=theta_deg,
        o_perp=o_perp,
        o_par=o_par,
        cell_size_km=cell_size_km,
    )

    A_inner = A_m.buffer(-buffer)
    if A_inner.is_empty:
        A_inner = A_m.buffer(0.0)

    ObstaclesBuf = [o.buffer(buffer) for o in Obstacles_m]

    free_space = A_inner
    if ObstaclesBuf:
        free_space = A_inner.difference(unary_union(ObstaclesBuf))

    if free_space.is_empty:
        return [], [], nx.Graph(), {}

    minx, miny, maxx, maxy = free_space.bounds
    bbox_metric = (minx, miny, maxx, maxy)

    if gridType == "SQUARE":
        P = regular_grid_centers(bbox_metric, DeltaPerp, DeltaPar)
    elif gridType == "HEX":
        P = hex_grid_centers(bbox_metric, DeltaPerp)
    else:
        P = regular_grid_centers(bbox_metric, DeltaPerp * 1.5, DeltaPar * 1.5)

    cells_m: List[Polygon] = []
    centroids_m: List[Tuple[float, float]] = []

    for cx, cy in P:
        if gridType == "SQUARE":
            C0 = square_cell((cx, cy), side=DeltaPerp)
        elif gridType == "HEX":
            C0 = hex_cell((cx, cy), pitch=DeltaPerp)
        else:
            C0 = square_cell((cx, cy), side=DeltaPerp * 1.2)

        C = C0.intersection(free_space)
        if C.is_empty:
            continue

        if isinstance(C, MultiPolygon):
            C = max(C.geoms, key=lambda g: g.area)

        if C.area < tauMinArea:
            continue

        cent = C.centroid
        if not cent.within(free_space):
            continue

        cells_m.append(C)
        centroids_m.append((cent.x, cent.y))

    if not cells_m:
        return [], [], nx.Graph(), {}

    subareas = boustrophedon_decompose(A_inner, ObstaclesBuf, sweep_angle_deg=0.0)
    phi_map = assign_orientation_to_cells(cells_m, subareas)

    G = build_adjacency_graph(cells_m, centroids_m, phi_map)

    cells_geo: List[Polygon] = []
    centroids_geo: List[LatLon] = []

    metric_to_geo = pyproj.Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)
    for idx, C_m in enumerate(cells_m):
        C_geo = project_to_geo_latlon(C_m)
        cells_geo.append(C_geo)

        cx_m, cy_m = centroids_m[idx]
        lon_c, lat_c = metric_to_geo.transform(cx_m, cy_m)
        centroids_geo.append((lat_c, lon_c))

    for idx, (lat_c, lon_c) in enumerate(centroids_geo):
        if idx in G.nodes:
            G.nodes[idx]["centroid_lat"] = lat_c
            G.nodes[idx]["centroid_lon"] = lon_c

    return cells_geo, centroids_geo, G, phi_map