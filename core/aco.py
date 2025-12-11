from __future__ import annotations
import random
from typing import List, Tuple, Callable, Sequence, Optional

from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.strtree import STRtree
from flask_socketio import emit
from core.extensions import socketio

Point = Tuple[float, float]

def _safe_polygons(nofly_raw):
    if not nofly_raw:
        return []

    polys = []
    for p in nofly_raw:
        if isinstance(p, Polygon):
            polys.append(p)
            continue

        if isinstance(p, (list, tuple)) and len(p) >= 3:
            try:
                coords = [(lng, lat) for lat, lng in p]
                poly = Polygon(coords)
                if poly.is_valid:
                    polys.append(poly)
            except Exception:
                continue

    return polys

def _precompute_energy_matrix(points, energy_fn):
    n = len(points)
    E = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            e = float(energy_fn(i, j))
            if e <= 0:
                e = 1e-6
            E[i][j] = E[j][i] = e
    return E


def _precompute_dist_matrix(points):
    n = len(points)
    D = [[0.0] * n for _ in range(n)]
    for i in range(n):
        lat_i, lon_i = points[i]
        for j in range(i + 1, n):
            lat_j, lon_j = points[j]
            d = ((lat_i - lat_j) ** 2 + (lon_i - lon_j) ** 2) ** 0.5
            D[i][j] = D[j][i] = d
    return D

def _safe_polygons(nofly_raw):
    polys = []

    if not nofly_raw:
        return polys

    for item in nofly_raw:
        if isinstance(item, Polygon):
            if item.is_valid and not item.is_empty:
                polys.append(item)
            continue

        if isinstance(item, (list, tuple)):
            if len(item) < 3:
                continue

            try:
                coords = [(lng, lat) for lat, lng in item]
                poly = Polygon(coords)

                if poly.is_valid and not poly.is_empty:
                    polys.append(poly)

            except Exception:
                continue

    return polys


def build_nofly_rtree(nofly_raw):
    polys = _safe_polygons(nofly_raw)

    if not polys:
        return None

    try:
        return STRtree(polys)
    except Exception:
        return None


def fast_segment_intersects(p1, p2, rtree):
    if rtree is None:
        return False

    try:
        seg = LineString([(p1[1], p1[0]), (p2[1], p2[0])])
        for poly in rtree.query(seg):
            if seg.intersects(poly):
                return True
        return False

    except Exception:
        return False

def _route_cost_from_E(t, E):
    return sum(E[u][v] for u, v in zip(t[:-1], t[1:])) if len(t) > 1 else 0.0


def _two_opt(tour, E, eff_budget):
    if len(tour) <= 4:
        return tour, _route_cost_from_E(tour, E)

    best = tour[:]
    best_cost = _route_cost_from_E(best, E)

    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for j in range(i + 2, len(best) - 1):
                cand = best[:]
                cand[i:j] = reversed(best[i:j])
                c = _route_cost_from_E(cand, E)
                if c < best_cost and c <= eff_budget:
                    best, best_cost = cand, c
                    improved = True
        socketio.sleep(0)

    return best, best_cost

def _clip_route_to_polygon(coords, poly: Optional[Polygon]):
    if poly is None or not coords:
        return coords

    line = LineString([(lon, lat) for lat, lon in coords])
    clipped = line.intersection(poly)

    if clipped.is_empty:
        return []

    if isinstance(clipped, LineString):
        return [(lat, lon) for lon, lat in clipped.coords]

    if isinstance(clipped, MultiLineString):
        out = []
        for g in clipped.geoms:
            out.extend([(lat, lon) for lon, lat in g.coords])
        return out

    return coords

def aco_orienteering(
    points: Sequence[Point],
    weights: Sequence[float],
    base_idx: int,
    energy_fn: Callable[[int, int], float],
    energy_back_fn: Callable[[int], float],
    energy_budget_wh: float,
    reserve_wh: float = 0.0,
    ants: int = 20,
    iterations: int = 20,
    alpha: float = 1.0,
    beta: float = 2.0,
    rho: float = 0.1,
    q0: float = 0.1,
    nofly=None,
    job_id=None,
    clip_polygon=None,
    dynamic_weather: bool = False,
    energy_refresh_interval: int = 5,
    energy_refresh_mode: str = "partial",
    energy_refresh_fraction: float = 0.15,
):
    import random

    n = len(points)
    if n == 0:
        return [], 0.0, 0.0

    if energy_budget_wh <= 0:
        energy_budget_wh = 1e12
        reserve_wh = 0.0

    eff_budget = max(0, energy_budget_wh - reserve_wh)

    E = _precompute_energy_matrix(points, energy_fn)
    D = _precompute_dist_matrix(points)

    rtree = build_nofly_rtree(nofly)

    tau = [[1.0 + random.random() * 0.02 for _ in range(n)] for _ in range(n)]

    def feasible(cur, nxt, used):
        if fast_segment_intersects(points[cur], points[nxt], rtree):
            return False
        c = E[cur][nxt]
        b = energy_back_fn(nxt)
        if c <= 0 or b <= 0:
            return False
        return used + c + b <= eff_budget

    g_best_tour = [base_idx, base_idx]
    g_best_score = 0.0
    g_best_cost = 1e12

    Q = 1.0

    for it in range(iterations):
        if dynamic_weather and it > 0 and energy_refresh_interval > 0:
            if it % energy_refresh_interval == 0:
                if energy_refresh_mode == "full":
                    E = _precompute_energy_matrix(points, energy_fn)
                    tau = [[t * 0.9 for t in row] for row in tau]
                else:
                    edges = max(1, int(energy_refresh_fraction * n * n))
                    for _ in range(edges):
                        i = random.randrange(n)
                        j = random.randrange(n)
                        if i != j:
                            e = float(energy_fn(i, j))
                            if e <= 0:
                                e = 1e-6
                            E[i][j] = E[j][i] = e
                    tau = [[t * 0.95 for t in row] for row in tau]

        i_best_tour = None
        i_best_score = -1
        i_best_cost = 1e12

        for a in range(ants):
            visited = [False] * n
            visited[base_idx] = True

            cur = base_idx
            used = 0.0
            score = 0.0
            tour = [base_idx]

            while True:
                cand = [j for j in range(n)
                        if j != base_idx and not visited[j] and feasible(cur, j, used)]

                if not cand:
                    break

                probs = []
                S = 0.0
                for j in cand:
                    eta = 1.0 / (D[cur][j] + 1e-12) ** beta
                    val = (tau[cur][j] ** alpha) * eta
                    probs.append((j, val))
                    S += val

                if S <= 0:
                    break

                if random.random() < q0:
                    chosen = max(cand,
                                 key=lambda j: (tau[cur][j] ** alpha) /
                                               ((D[cur][j] + 1e-12) ** beta))
                else:
                    r = random.random() * S
                    acc = 0.0
                    chosen = cand[-1]
                    for j, v in probs:
                        acc += v
                        if acc >= r:
                            chosen = j
                            break

                used += E[cur][chosen]
                score += weights[chosen]
                visited[chosen] = True
                tour.append(chosen)
                cur = chosen

            used += energy_back_fn(cur)
            tour.append(base_idx)

            if used <= eff_budget:
                if score > i_best_score or (
                    score == i_best_score and used < i_best_cost
                ):
                    i_best_tour = tour
                    i_best_score = score
                    i_best_cost = used

        if i_best_tour is None:
            socketio.sleep(0.01)
            continue

        i_best_tour, i_best_cost = _two_opt(i_best_tour, E, eff_budget)

        if (i_best_score > g_best_score) or (
            i_best_score == g_best_score and i_best_cost < g_best_cost
        ):
            g_best_score = i_best_score
            g_best_cost = i_best_cost
            g_best_tour = i_best_tour[:]

        for i in range(n):
            for j in range(n):
                tau[i][j] *= (1 - rho)

        d = Q / (i_best_cost + 1e-9)
        for u, v in zip(i_best_tour[:-1], i_best_tour[1:]):
            tau[u][v] += d
            tau[v][u] += d

        coords_best = [points[i] for i in g_best_tour]
        coords_best = _clip_route_to_polygon(coords_best, clip_polygon)

        coords_iter = [points[i] for i in i_best_tour]
        coords_iter = _clip_route_to_polygon(coords_iter, clip_polygon)

        emit("planner_update", {
            "event": "aco_iter",
            "iteration": it + 1,
            "iter_score": float(i_best_score),
            "iter_cost": float(i_best_cost),
            "iter_tour": coords_iter,
            "best_score": float(g_best_score),
            "best_cost": float(g_best_cost),
            "best_tour": coords_best,
        })

        socketio.sleep(0)

    if g_best_score <= 0 or len(g_best_tour) <= 2:
        order = sorted(
            [i for i in range(n) if i != base_idx],
            key=lambda i: weights[i], reverse=True
        )
        t = [base_idx]
        cur = base_idx
        used = 0
        score = 0

        for j in order:
            c = E[cur][j]
            b = energy_back_fn(j)
            if used + c + b > eff_budget:
                continue
            used += c
            score += weights[j]
            t.append(j)
            cur = j

        used += energy_back_fn(cur)
        t.append(base_idx)

        g_best_tour = t
        g_best_score = score
        g_best_cost = used

    return g_best_tour, float(g_best_score), float(g_best_cost)