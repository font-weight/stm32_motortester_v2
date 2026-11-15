"""Deterministic, single-copper-layer grid router for the R5.3 layout draft.

All dimensions are millimetres. Input/output are JSON; this utility does not
alter KiCad files. Exact centre-line clearance is checked against inflated
copper shapes on every A* edge, including diagonal edges and pad escapes.
KiCad DRC remains the authority for the resulting physical PCB.

Usage: python router.py layout.json routes.json
Import: result = route(document)
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
from collections import defaultdict
from pathlib import Path

EPS = 1e-9
SQRT2 = math.sqrt(2.0)


def _point_segment2(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den)) if den else 0.0
    return (p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2


def _segments2(a, b, c, d):
    """Squared distance between two closed segments, including intersections."""
    def cross(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
    if cross(a, b, c) * cross(a, b, d) <= 0 and cross(c, d, a) * cross(c, d, b) <= 0:
        if (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) + EPS
                and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1])) + EPS):
            return 0.0
    return min(_point_segment2(a, c, d), _point_segment2(b, c, d),
               _point_segment2(c, a, b), _point_segment2(d, a, b))


def _segment_rect2(a, b, hw, hh):
    if (-hw <= a[0] <= hw and -hh <= a[1] <= hh) or (-hw <= b[0] <= hw and -hh <= b[1] <= hh):
        return 0.0
    corners = ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))
    return min(_segments2(a, b, corners[i], corners[(i + 1) % 4]) for i in range(4))


class Shape:
    """Capsule or rotated rectangle, with clearance added as Minkowski radius."""
    def __init__(self, kind, center, hw, hh, angle=0.0, radius=0.0, end=None):
        self.kind, self.center, self.hw, self.hh = kind, tuple(center), hw, hh
        self.cos, self.sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        self.radius = radius
        self.end = tuple(end) if end is not None else self.center
        if kind == "segment":
            self.bounds = (min(center[0], self.end[0]) - radius, min(center[1], self.end[1]) - radius,
                           max(center[0], self.end[0]) + radius, max(center[1], self.end[1]) + radius)
        elif kind == "circle":
            extent = max(hw, hh) + radius
            self.bounds = (center[0] - extent, center[1] - extent, center[0] + extent, center[1] + extent)
        else:
            ex, ey = abs(self.cos) * hw + abs(self.sin) * hh + radius, abs(self.sin) * hw + abs(self.cos) * hh + radius
            self.bounds = (center[0] - ex, center[1] - ey, center[0] + ex, center[1] + ey)

    def local(self, p):
        x, y = p[0] - self.center[0], p[1] - self.center[1]
        return x * self.cos + y * self.sin, -x * self.sin + y * self.cos

    def collision(self, a, b):
        if self.kind == "segment":
            distance2 = _segments2(a, b, self.center, self.end)
            radius = self.radius
        else:
            a, b = self.local(a), self.local(b)
            radius = self.radius
            if self.kind == "circle":
                distance2 = _point_segment2((0.0, 0.0), a, b)
                radius += max(self.hw, self.hh)
            elif self.kind == "oval":
                if self.hw >= self.hh:
                    c, d = (self.hh - self.hw, 0.0), (self.hw - self.hh, 0.0)
                else:
                    c, d = (0.0, self.hw - self.hh), (0.0, self.hh - self.hw)
                distance2 = _segments2(a, b, c, d)
                radius += min(self.hw, self.hh)
            else:
                distance2 = _segment_rect2(a, b, self.hw, self.hh)
        # Equality is allowed: input clearance is the requested minimum gap.
        return distance2 < radius * radius - EPS or (radius == 0 and distance2 <= EPS)


def _pad_shape(pad, inflation=0.0):
    return Shape(pad.get("shape", "rect"), (float(pad["x"]), float(pad["y"])),
                 float(pad["w"]) / 2, float(pad["h"]) / 2,
                 float(pad.get("angle", pad.get("rotation", 0))), inflation)


class BoardSpace:
    def __init__(self, document, net, tracks):
        self.grid = float(document.get("grid", 0.5))
        self.width = float(document.get("track_width", 1.2))
        self.clearance = float(document.get("clearance", 0.75))
        self.bounds = tuple(float(v) for v in document["bounds"])
        if self.grid <= 0 or self.width <= 0 or self.clearance < 0:
            raise ValueError("grid and track_width must be positive; clearance must be non-negative")
        x0, y0, x1, y1 = self.bounds
        if x1 <= x0 or y1 <= y0:
            raise ValueError("bounds must have positive width and height")
        self.nx, self.ny = int(math.floor((x1 - x0) / self.grid)) + 1, int(math.floor((y1 - y0) / self.grid)) + 1
        self.shapes = []
        inflate = self.width / 2 + self.clearance
        for pad in document["pads"]:
            if pad.get("net") != net:
                self.shapes.append(_pad_shape(pad, inflate))
        for track in tracks:
            if track.get("net") == net:
                continue
            points = track["points"]
            radius = float(track.get("width", self.width)) / 2 + inflate
            for a, b in zip(points, points[1:]):
                self.shapes.append(Shape("segment", a, 0, 0, radius=radius, end=b))
        for obstacle in document.get("obstacles", []):
            if isinstance(obstacle, (list, tuple)):
                xa, ya, xb, yb = obstacle
                obstacle = {"x": (xa + xb) / 2, "y": (ya + yb) / 2, "w": xb - xa, "h": yb - ya, "shape": "rect"}
            elif "bounds" in obstacle:
                xa, ya, xb, yb = obstacle["bounds"]
                obstacle = dict(obstacle, x=(xa + xb) / 2, y=(ya + yb) / 2, w=xb - xa, h=yb - ya)
            # Obstacles are copper keepouts; use clearance unless explicitly
            # supplied as a centre-line keepout (inflation=0).
            self.shapes.append(_pad_shape(obstacle, float(obstacle.get("inflation", inflate))))
        self.bucket_size = max(4.0, 4 * self.grid)
        self.buckets = defaultdict(list)
        self.blocked = bytearray(self.nx * self.ny)
        for index, shape in enumerate(self.shapes):
            xa, ya, xb, yb = shape.bounds
            for by in range(math.floor(ya / self.bucket_size), math.floor(yb / self.bucket_size) + 1):
                for bx in range(math.floor(xa / self.bucket_size), math.floor(xb / self.bucket_size) + 1):
                    self.buckets[(bx, by)].append(index)
            ia, ib = max(0, int(math.ceil((xa - x0) / self.grid))), min(self.nx - 1, int(math.floor((xb - x0) / self.grid)))
            ja, jb = max(0, int(math.ceil((ya - y0) / self.grid))), min(self.ny - 1, int(math.floor((yb - y0) / self.grid)))
            for iy in range(ja, jb + 1):
                for ix in range(ia, ib + 1):
                    node = iy * self.nx + ix
                    if not self.blocked[node]:
                        p = self.point(node)
                        if shape.collision(p, p):
                            self.blocked[node] = 1
        # Bounds are physical board edges. Copper must stay inside by at least
        # half its width; add edge_clearance if a fabrication margin is wanted.
        self.margin = self.width / 2 + float(document.get("edge_clearance", self.clearance))
        for iy in range(self.ny):
            for ix in range(self.nx):
                p = (x0 + ix * self.grid, y0 + iy * self.grid)
                if not self.in_bounds(p):
                    self.blocked[iy * self.nx + ix] = 1
        self.edge_cache = {}

    def point(self, node):
        return self.bounds[0] + (node % self.nx) * self.grid, self.bounds[1] + (node // self.nx) * self.grid

    def in_bounds(self, p):
        x0, y0, x1, y1 = self.bounds
        return x0 + self.margin - EPS <= p[0] <= x1 - self.margin + EPS and y0 + self.margin - EPS <= p[1] <= y1 - self.margin + EPS

    def clear(self, a, b):
        if not self.in_bounds(a) or not self.in_bounds(b):
            return False
        seen = set()
        for by in range(math.floor(min(a[1], b[1]) / self.bucket_size), math.floor(max(a[1], b[1]) / self.bucket_size) + 1):
            for bx in range(math.floor(min(a[0], b[0]) / self.bucket_size), math.floor(max(a[0], b[0]) / self.bucket_size) + 1):
                for index in self.buckets.get((bx, by), ()):
                    if index not in seen:
                        seen.add(index)
                        if self.shapes[index].collision(a, b):
                            return False
        return True

    def anchors(self, pad):
        center = (float(pad["x"]), float(pad["y"]))
        shape = _pad_shape(pad)
        xa, ya, xb, yb = shape.bounds
        candidates = []
        for iy in range(max(0, math.ceil((ya - self.bounds[1]) / self.grid)), min(self.ny - 1, math.floor((yb - self.bounds[1]) / self.grid)) + 1):
            for ix in range(max(0, math.ceil((xa - self.bounds[0]) / self.grid)), min(self.nx - 1, math.floor((xb - self.bounds[0]) / self.grid)) + 1):
                node = iy * self.nx + ix
                p = self.point(node)
                if not self.blocked[node] and shape.collision(p, p) and self.clear(center, p):
                    candidates.append((math.dist(center, p), node))
        # Tiny/non-grid pads can still escape to a nearby grid node, with the
        # complete pad-centre segment checked for copper clearance.
        if not candidates:
            ix0, iy0 = round((center[0] - self.bounds[0]) / self.grid), round((center[1] - self.bounds[1]) / self.grid)
            for iy in range(max(0, iy0 - 1), min(self.ny - 1, iy0 + 1) + 1):
                for ix in range(max(0, ix0 - 1), min(self.nx - 1, ix0 + 1) + 1):
                    node = iy * self.nx + ix
                    p = self.point(node)
                    if not self.blocked[node] and self.clear(center, p):
                        candidates.append((math.dist(center, p), node))
        return sorted(candidates)

    def search(self, source, target, limit=None):
        starts, ends = self.anchors(source), self.anchors(target)
        if not starts or not ends:
            return None, 0
        goals = {node: distance for distance, node in ends}
        tx, ty = float(target["x"]), float(target["y"])
        # Euclidean distance to the exact target is admissible, including the
        # final short segment from the grid into the actual pad centre.
        def heuristic(node):
            x, y = self.point(node)
            return math.hypot(x - tx, y - ty)
        heap, distance, previous = [], {}, {}
        for cost, node in starts:
            if cost < distance.get(node, math.inf):
                distance[node] = cost
                previous[node] = None
                heapq.heappush(heap, (cost + heuristic(node), cost, node))
        best_node, best_cost, visited = None, math.inf, 0
        steps = ((1, 0, 1.0), (0, 1, 1.0), (-1, 0, 1.0), (0, -1, 1.0),
                 (1, 1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2), (1, -1, SQRT2))
        while heap:
            priority, cost, node = heapq.heappop(heap)
            if cost > distance[node] + EPS:
                continue
            if priority >= best_cost - EPS:
                break
            visited += 1
            if limit is not None and visited > limit:
                return None, visited
            if node in goals:
                total = cost + goals[node]
                if total < best_cost:
                    best_node, best_cost = node, total
                continue
            ix, iy = node % self.nx, node // self.nx
            for dx, dy, scale in steps:
                jx, jy = ix + dx, iy + dy
                if not 0 <= jx < self.nx or not 0 <= jy < self.ny:
                    continue
                adjacent = jy * self.nx + jx
                if self.blocked[adjacent]:
                    continue
                parent = previous[node]
                turn = 0.0
                if parent is not None:
                    pdx, pdy = ix - parent % self.nx, iy - parent // self.nx
                    if (pdx, pdy) != (dx, dy):
                        turn = self.grid * 0.02
                new_cost = cost + scale * self.grid + turn
                if new_cost >= distance.get(adjacent, math.inf) - EPS:
                    continue
                pair = (min(node, adjacent), max(node, adjacent))
                valid = self.edge_cache.get(pair)
                if valid is None:
                    valid = self.clear(self.point(node), self.point(adjacent))
                    self.edge_cache[pair] = valid
                if not valid:
                    continue
                distance[adjacent], previous[adjacent] = new_cost, node
                heapq.heappush(heap, (new_cost + heuristic(adjacent), new_cost, adjacent))
        if best_node is None:
            return None, visited
        points = []
        while best_node is not None:
            points.append(self.point(best_node))
            best_node = previous[best_node]
        points.reverse()
        points = [(float(source["x"]), float(source["y"]))] + points + [(tx, ty)]
        points = _compress(points)
        # Remove unnecessary staircase corners while retaining 0/45/90 degree
        # grid segments. Exact off-grid pad escapes remain as short segments.
        smooth, current = [points[0]], 0
        while current < len(points) - 1:
            chosen = current + 1
            for candidate in range(len(points) - 1, current + 1, -1):
                a, b = points[current], points[candidate]
                dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
                if (dx < EPS or dy < EPS or abs(dx - dy) < EPS) and self.clear(a, b):
                    chosen = candidate
                    break
            smooth.append(points[chosen])
            current = chosen
        return _compress(smooth), visited


def _compress(points):
    compressed = []
    for p in points:
        if compressed and math.dist(compressed[-1], p) < EPS:
            continue
        while len(compressed) >= 2:
            a, b = compressed[-2], compressed[-1]
            dx1, dy1, dx2, dy2 = b[0] - a[0], b[1] - a[1], p[0] - b[0], p[1] - b[1]
            if abs(dx1 * dy2 - dy1 * dx2) <= EPS and dx1 * dx2 + dy1 * dy2 >= 0:
                compressed.pop()
            else:
                break
        compressed.append(p)
    return [[round(x, 6), round(y, 6)] for x, y in compressed]


def _declared_pad_connections(document):
    """Resolve explicit existing connections without inventing new copper.

    Entries use ref.pin identifiers. Groups must refer to known pads of one
    net; this prevents an accidental cross-net jumper declaration from hiding
    a missing connection. KiCad verification still checks the physical bridge.
    """
    pads = document["pads"]
    by_id = defaultdict(list)
    for pad in pads:
        by_id[f"{pad.get('ref')}.{pad.get('pin')}"].append(pad)
    parent = {key: key for key in by_id}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    groups = document.get("connected_pad_groups", [])
    for group in groups:
        if not isinstance(group, (list, tuple)) or any(not isinstance(key, str) for key in group):
            raise ValueError("connected_pad_groups must contain lists of ref.pin strings")
        unknown = [key for key in group if key not in by_id]
        if unknown:
            raise ValueError("connected_pad_groups references unknown pads: " + ", ".join(unknown))
        nets = {pad.get("net") for key in group for pad in by_id[key]}
        if len(nets) > 1 or any(net in (None, "", 0) for net in nets):
            raise ValueError("declared pad connection must contain known pads on one nonempty net")
        for key in group[1:]:
            parent[find(key)] = find(group[0])
    return {key: find(key) for key in by_id}


def route(document):
    """Route optional forests; explicit groups/pretracks never create copper.

    Defaults preserve the original first-component routing behavior. With
    forest=True, each reachable component is routed and failed lists a minimal
    spanning set of *unresolved* bridges, not a claim of physical connection.
    max_detour_ratio is a positive number or a {net: number} mapping. The
    optional max_detour_floor_mm (default 15) permits short pad escapes.
    """
    declared = _declared_pad_connections(document)
    pads_by_net = defaultdict(list)
    for pad in document["pads"]:
        if pad.get("net") not in (None, "", 0):
            pads_by_net[pad["net"]].append(pad)
    forest = bool(document.get("forest", False))
    detour = document.get("max_detour_ratio")
    if detour is not None:
        ratios = detour.values() if isinstance(detour, dict) else [detour]
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in ratios):
            raise ValueError("max_detour_ratio must be positive finite numbers")
    floor = float(document.get("max_detour_floor_mm", 15.0))
    if not math.isfinite(floor) or floor < 0:
        raise ValueError("max_detour_floor_mm must be finite and non-negative")
    skip = set(document.get("skip_nets", []))
    order = list(dict.fromkeys(document.get("route_order", [])))
    order.extend(sorted((n for n in pads_by_net if n not in order), key=str))
    tracks = list(document.get("pretracks", []))
    routes, failed, diagnostics = [], [], []
    for net in order:
        pads = pads_by_net.get(net, [])
        if net in skip or len(pads) < 2:
            continue
        space = BoardSpace(document, net, tracks)
        ratio = detour.get(net) if isinstance(detour, dict) else detour
        members = defaultdict(set)
        for index, pad in enumerate(pads):
            members[declared[f"{pad.get('ref')}.{pad.get('pin')}"]].add(index)
        equivalence = {}
        for component in members.values():
            for index in component:
                equivalence[index] = component
        def closure(indices):
            return set().union(*(equivalence[index] for index in indices)) if indices else set()
        def endpoint(index):
            return [pads[index].get("ref"), str(pads[index].get("pin"))]
        def direct(a, b):
            return math.hypot(pads[a]["x"] - pads[b]["x"], pads[a]["y"] - pads[b]["y"])
        def pair_key(a, b):
            return min(a, b), max(a, b)
        pending, components, attempt_failures = set(range(len(pads))), [], {}
        expanded, rejected_detours = 0, 0
        while pending:
            connected = closure({min(pending)})
            pending.difference_update(connected)
            attempted = set()
            while pending:
                connected = closure(connected)
                pending.difference_update(connected)
                pairs = sorted((direct(a, b), a, b)
                               for a in connected for b in pending if (a, b) not in attempted)
                if not pairs:
                    break
                separation, a, b = pairs[0]
                attempted.add((a, b))
                limit = document.get("max_expansions")
                points, visits = space.search(pads[a], pads[b], limit)
                expanded += visits
                if points is None:
                    reason = "search expansion limit reached" if limit is not None and visits > limit else "no clearance-valid grid path"
                    attempt_failures[pair_key(a, b)] = {"reason": reason}
                    continue
                length = sum(math.dist(x, y) for x, y in zip(points, points[1:]))
                maximum = max(floor, ratio * separation) if ratio is not None else None
                if maximum is not None and length > maximum + EPS:
                    rejected_detours += 1
                    attempt_failures[pair_key(a, b)] = {
                        "reason": "clearance-valid path rejected by detour limit",
                        "candidate_length_mm": length, "allowed_length_mm": maximum,
                        "straight_distance_mm": separation, "max_detour_ratio": ratio}
                    continue
                item = {"net": net, "width": space.width, "points": points,
                        "from": endpoint(a), "to": endpoint(b)}
                routes.append(item)
                tracks.append(item)
                connected = closure(connected | {b})
                pending.difference_update(connected)
            components.append(connected)
            if not forest:
                break
        if forest:
            joined, remaining = set(components[0]), list(components[1:])
            while remaining:
                separation, a, b, component_index = min(
                    (direct(a, b), a, b, index)
                    for a in joined for index, component in enumerate(remaining) for b in component)
                detail = attempt_failures.get(pair_key(a, b), {"reason": "no accepted route between routing components"})
                failed.append({"net": net, "from": endpoint(a), "to": endpoint(b),
                               "straight_distance_mm": separation, **detail,
                               "unresolved_component_bridge": True})
                joined.update(remaining.pop(component_index))
            unresolved_pads = sum(len(component) for component in components[1:])
        else:
            for b in sorted(pending):
                a = min(connected, key=lambda index: (direct(index, b), index))
                detail = attempt_failures.get(pair_key(a, b), {"reason": "no clearance-valid grid path"})
                failed.append({"net": net, "from": endpoint(a), "to": endpoint(b), **detail})
            unresolved_pads = len(pending)
        diagnostics.append({"net": net, "pads": len(pads), "unconnected_pads": unresolved_pads,
                            "expanded_nodes": expanded, "rejected_detour_attempts": rejected_detours,
                            "components": [[endpoint(index) for index in sorted(component)] for component in components],
                            "unresolved_component_bridges": len(components) - 1 if forest else None})
    return {"routes": routes, "failed": failed, "diagnostics": diagnostics,
            "grid_mm": document.get("grid", 0.5), "clearance_mm": document.get("clearance", 0.75),
            "forest": forest, "declared_connected_pad_groups": document.get("connected_pad_groups", []),
            "layer": "B.Cu", "note": "Draft geometric routes; declared connections must physically exist. Verify actual KiCad pad shapes, connectivity, clearances and zones with DRC."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8-sig"))
    result = route(document)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"routes": len(result["routes"]), "failed": len(result["failed"]), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
