"""Read-only ground-island export and straight jumper proposals for R5.2.

Run with D:/Programs/bin/python.exe (pcbnew). The analysis subprocess uses
the project's Python and existing Shapely dependency; no PCB is saved/edited.
"""
from pathlib import Path
import hashlib
import json
import math
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "build/analog-r52-pcb"
OUT = WORK / "ground-analysis"
BOARD = ROOT / "hardware/v2-input/r52-lut-20261102/analog-input-r52.kicad_pcb"


def export_geometry():
    import pcbnew as p
    OUT.mkdir(parents=True, exist_ok=True)
    payload = BOARD.read_bytes()
    snapshot = OUT / "source-candidate.kicad_pcb"
    snapshot.write_bytes(payload)
    b = p.LoadBoard(str(snapshot))
    def pt(value):
        return [p.ToMM(value.x), p.ToMM(value.y)]
    def chain(value):
        return [pt(value.CPoint(i)) for i in range(value.PointCount())]
    def polygons(value):
        return [{"outer": chain(value.COutline(i)),
                 "holes": [chain(value.CHole(i, j)) for j in range(value.HoleCount(i))]}
                for i in range(value.OutlineCount())]
    zones, pads, tracks, footprints = [], [], [], []
    for zone in b.Zones():
        if zone.GetIsRuleArea() or zone.GetNetname() != "AGND":
            continue
        if not zone.IsFilled() or not zone.HasFilledPolysForLayer(p.B_Cu):
            raise RuntimeError("AGND zone is not filled; root must fill/save before analysis")
        zones.extend(polygons(zone.GetFilledPolysList(p.B_Cu)))
    if not zones:
        raise RuntimeError("AGND filled polygons missing; intermediate board rejected")
    for fp in b.GetFootprints():
        fp.BuildCourtyardCaches()
        footprints.append({"ref": fp.GetReference(), "position": pt(fp.GetPosition()),
                           "layer": b.GetLayerName(fp.GetLayer()),
                           "native_jumper": fp.GetDuplicatePadNumbersAreJumpers(),
                           "top_courtyard": polygons(fp.GetCourtyard(p.F_CrtYd)),
                           "bottom_courtyard": polygons(fp.GetCourtyard(p.B_CrtYd))})
        for pad in fp.Pads():
            pads.append({"ref": fp.GetReference(), "pin": pad.GetNumber(), "net": pad.GetNetname(),
                         "position": pt(pad.GetPosition()), "size": pt(pad.GetSize()),
                         "drill": pt(pad.GetDrillSize()), "copper": polygons(pad.GetEffectivePolygon(p.B_Cu))})
    for track in b.GetTracks():
        if track.GetLayer() != p.B_Cu:
            continue
        tracks.append({"net": track.GetNetname(), "width": p.ToMM(track.GetWidth()),
                       "a": pt(track.GetStart()), "b": pt(track.GetEnd())})
    if BOARD.read_bytes() != payload:
        raise RuntimeError("Root board changed while exporting; retry a stable filled candidate")
    data = {"board": str(BOARD), "board_sha256": hashlib.sha256(payload).hexdigest(),
            "zone_polygons": zones, "pads": pads, "tracks": tracks, "footprints": footprints,
            "scope": "Read-only existing filled copper; original polygon contours/holes retained. No physical verification."}
    (OUT / "geometry.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({"exported_zones": len(zones), "pads": len(pads), "footprints": len(footprints),
                      "source_sha256": data["board_sha256"]}), flush=True)
    if "--export-only" not in sys.argv:
        subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), str(Path(__file__).resolve()), "--final-analyze" if "--final-check" in sys.argv else "--analyze"], check=True)


def analyze():
    sys.path.insert(0, str(WORK / "deps"))
    import numpy as np
    import shapely as s
    from shapely.geometry import Polygon, Point, LineString, MultiPolygon
    from shapely.ops import unary_union
    data = json.loads((OUT / "geometry.json").read_text())
    def polygon_parts(geometry):
        if geometry.geom_type == "Polygon":
            return [geometry]
        if hasattr(geometry, "geoms"):
            return [part for item in geometry.geoms for part in polygon_parts(item)]
        return []
    def to_shape(records):
        parts = []
        for record in records:
            if len(record["outer"]) >= 3:
                raw = Polygon(record["outer"], record["holes"])
                parts.extend(polygon_parts(s.make_valid(raw)))
        return unary_union(parts)
    def record(geometry):
        return [{"outer": [list(pt) for pt in poly.exterior.coords],
                 "holes": [[list(pt) for pt in ring.coords] for ring in poly.interiors]}
                for poly in polygon_parts(geometry)]
    zone = to_shape(data["zone_polygons"])
    copper = [zone]
    groundpads = []
    for pad in data["pads"]:
        if pad["net"] == "AGND":
            shape = to_shape(pad["copper"])
            groundpads.append((pad, shape))
            copper.append(shape)
    for track in data["tracks"]:
        if track["net"] == "AGND":
            copper.append(LineString([track["a"], track["b"]]).buffer(track["width"] / 2, quad_segs=24))
    ground = unary_union(copper)
    islands = sorted(polygon_parts(ground), key=lambda poly: (-poly.area, poly.centroid.x, poly.centroid.y))
    footprints = [(fp["ref"], to_shape(fp["top_courtyard"])) for fp in data["footprints"] if fp["top_courtyard"]]
    top_keepout = unary_union([shape for _, shape in footprints])
    pad_keepout = top_keepout.buffer(1.8, quad_segs=16)
    memberships = []
    island_info = []
    for index, island in enumerate(islands):
        contained = []
        for pad, shape in groundpads:
            if island.intersection(shape).area > 1e-7:
                name = f"{pad['ref']}.{pad['pin']}"
                contained.append(name)
                memberships.append({"pad": name, "position": pad["position"], "island": index})
        core = island.buffer(-0.499, quad_segs=16)
        coreparts = polygon_parts(core)
        coregroups = []
        for corepart in coreparts:
            names = []
            for member in memberships:
                if member["island"] == index and corepart.distance(Point(member["position"])) <= 0.51:
                    names.append(member["pad"])
            if names:
                coregroups.append(names)
        island_info.append({"island": index, "area_mm2": island.area, "bounds": list(island.bounds),
                            "ground_pads": contained, "holes_after_polygon_reconstruction": len(island.interiors),
                            "core_groups_at_0_998mm_neck": coregroups,
                            "neck_scope": "Morphological screen: erode 0.499 mm; populated core groups can reveal sub-1 mm necks. Pad drill annuli not subtracted; not a manufacturing guarantee."})
    # Candidate pad discs stay entirely inside current AGND copper, so adding
    # the proposed 2.6 mm pad cannot reduce copper clearance to another net.
    # Courtyard radius 1.8 mm is intentionally larger than the copper radius.
    xv, yv = np.meshgrid(np.arange(12, 151, .5), np.arange(12, 107, .5))
    all_points = np.column_stack((xv.ravel(), yv.ravel()))
    point_shapes = s.points(all_points)
    candidates = []
    for island in islands:
        allowed = island.buffer(-1.301, quad_segs=24).difference(pad_keepout)
        mask = s.contains(allowed, point_shapes).reshape(xv.shape)
        # Only boundary grid cells are needed for shortest inter-island wires.
        inner = mask.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            inner &= np.roll(mask, (dy, dx), (0, 1))
        boundary = mask & ~inner
        candidates.append(all_points[boundary.ravel()])
    def wire_courtyard(a, b):
        a, b = np.asarray(a), np.asarray(b)
        delta = b - a
        length = np.linalg.norm(delta)
        u = delta / length
        n = np.array([-u[1], u[0]])
        sequence = [(-1.8,-1.8),(1.8,-1.8),(1.8,-.8),(length-1.8,-.8),(length-1.8,-1.8),(length+1.8,-1.8),
                    (length+1.8,1.8),(length-1.8,1.8),(length-1.8,.8),(1.8,.8),(1.8,1.8),(-1.8,1.8)]
        return Polygon([a + u * t + n * side for t, side in sequence])
    pair_options = {}
    for i in range(len(islands)):
        for j in range(i + 1, len(islands)):
            left, right = candidates[i], candidates[j]
            if not len(left) or not len(right):
                pair_options[(i, j)] = []
                continue
            pairs = []
            for start in range(0, len(left), 64):
                block = left[start:start + 64]
                squared = ((block[:, None, :] - right[None, :, :]) ** 2).sum(axis=2)
                count = min(500, squared.size)
                indices = np.argpartition(squared.ravel(), count - 1)[:count]
                for flat in indices:
                    li, ri = divmod(int(flat), len(right))
                    pairs.append((float(squared[li, ri]), start + li, ri))
            options = []
            for squared, li, ri in sorted(pairs):
                a, b = left[li], right[ri]
                if math.sqrt(squared) < 4:
                    continue
                courtyard = wire_courtyard(a, b)
                if courtyard.intersects(top_keepout):
                    continue
                # Keep alternatives geometrically distinct for joint selection.
                if any(np.linalg.norm(a - opt["a"]) < 2 and np.linalg.norm(b - opt["b"]) < 2 for opt in options):
                    continue
                options.append({"islands": [i, j], "a": a.tolist(), "b": b.tolist(),
                                "length_mm": math.sqrt(squared), "courtyard": courtyard})
                if len(options) >= 20:
                    break
            pair_options[(i, j)] = options
    proposals = []
    flat_options = [option for options in pair_options.values() for option in options]
    if len(islands) == 3:
        for ai, a in enumerate(flat_options):
            for b in flat_options[ai + 1:]:
                if len(set(a["islands"]) | set(b["islands"])) != 3 or a["islands"] == b["islands"]:
                    continue
                if a["courtyard"].intersects(b["courtyard"]):
                    continue
                proposals.append((a["length_mm"] + b["length_mm"], a, b))
        proposals.sort(key=lambda item: (item[0], item[1]["a"], item[2]["a"]))
    def serial(option):
        return {key: value for key, value in option.items() if key != "courtyard"}
    best = [serial(option) for option in proposals[0][1:]] if proposals else []
    result = {"board_sha256": data["board_sha256"], "islands": island_info, "ground_pad_membership": memberships,
              "ground_polygons": record(ground), "top_courtyards": [{"ref": ref, "polygons": record(shape)} for ref, shape in footprints],
              "candidate_counts": [len(points) for points in candidates],
              "pair_options": {f"{i}-{j}": [serial(option) for option in options] for (i, j), options in pair_options.items()},
              "best_two_wires": best, "total_wire_length_mm": proposals[0][0] if proposals else None,
              "pad_diameter_mm": 2.6, "drill_mm": 1.0, "wire_courtyard_half_width_mm": .8,
              "scope": "Geometric proposal only. Pads fully inside existing AGND copper; straight wire courtyards avoid all top courtyards including existing W1. Bottom C5 allowed. Root must add actual footprints/refill/DRC and repeat on final board."}
    (OUT / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# Геометрия AGND и предложения перемычек", "", f"Исходная PCB SHA256: `{data['board_sha256']}`.", "",
             "Экспорт прочитал сохранённую заливку; CAD не изменён. В `geometry.json` исходные контуры/отверстия, в `analysis.json` восстановленные полигоны, принадлежность площадок и Courtyard.", ""]
    for info in island_info:
        lines += [f"- Остров {info['island']}: {info['area_mm2']:.1f} мм²; площадки: {', '.join(info['ground_pads'])}.",
                  f"  Группы площадок после морфологического сужения на 0,499 мм: {info['core_groups_at_0_998mm_neck']}."]
    lines += ["", "## Две прямые изолированные перемычки", ""]
    if best:
        for index, wire in enumerate(best, 1):
            lines.append(f"{index}. Острова {wire['islands']}: {wire['a']} → {wire['b']}, длина {wire['length_mm']:.2f} мм.")
        lines += ["", f"Общая длина {proposals[0][0]:.2f} мм. Отдельные круглые площадки Ø2,6 мм, отверстия Ø1 мм. Площадки целиком внутри имеющейся меди AGND; прямые верхние Courtyard перемычек не пересекают верхние Courtyard деталей, друг друга и W1. C5 снизу не препятствует верхней перемычке."]
    else:
        lines.append("В ограниченном поиске не найден комплект двух допустимых прямых перемычек; CAD не изменялся.")
    lines += ["", "Морфологическая проверка 0,998 мм — только поиск потенциальных узких перешейков; сверление площадок не вычтено. Число min_thickness в проекте само по себе не доказывает достаточную ширину каждого физического возврата. Повторить на окончательной заливке после изменений питания/переключателя и DRC; разрешения на изготовление этот анализ не даёт."]
    (OUT / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"islands": len(islands), "pad_membership": memberships, "best_two_wires": best,
                      "total_wire_length_mm": result["total_wire_length_mm"]}), flush=True)



def estimate_return_paths(ground, wires, membership, tracks=()):
    """Bounded A* on a 0.5 mm grid, copper corridor radius about 0.5 mm.

    Wire edges are actual native jumper endpoints. This is geometry, not an
    impedance or high-frequency current-distribution model. Grid sampling can
    overestimate length; no false copper is added and off-grid ends are exact.
    """
    import heapq
    import numpy as np
    import shapely as s
    from shapely.geometry import Point, LineString
    source = next(row["at"] for row in membership if row["ref"] == "C6" and row["pin"] == "2")
    target = next(row["at"] for row in membership if row["ref"] == "U1" and row["pin"] == "11")
    grid = .5
    radius = .5 - .00001
    core = ground.buffer(-radius, quad_segs=32)
    s.prepare(core)
    xmin, ymin, xmax, ymax = ground.bounds
    x0, y0 = math.floor(xmin / grid) * grid, math.floor(ymin / grid) * grid
    nx, ny = math.ceil((xmax - x0) / grid) + 1, math.ceil((ymax - y0) / grid) + 1
    xv, yv = np.meshgrid(x0 + np.arange(nx) * grid, y0 + np.arange(ny) * grid)
    coordinates = np.column_stack((xv.ravel(), yv.ravel()))
    allowed = s.covers(core, s.points(coordinates))
    count = len(coordinates)
    specials = [source, target] + [row[side]["at"] for row in wires for side in ["a", "b"]]
    # Keep real track endpoints as auxiliary nodes. A 1.2 mm track at x=94.75
    # has a valid 1 mm corridor which a 0.5 mm Cartesian grid can miss entirely.
    track_start = len(specials)
    for track in tracks:
        specials.extend([track["a"], track["b"]])
    anchor_edges = {}
    for index, pos in enumerate(specials):
        node = count + index
        ix0, iy0 = round((pos[0] - x0) / grid), round((pos[1] - y0) / grid)
        for iy in range(max(0, iy0 - 2), min(ny, iy0 + 3)):
            for ix in range(max(0, ix0 - 2), min(nx, ix0 + 3)):
                other = iy * nx + ix
                if allowed[other] and core.covers(LineString([pos, coordinates[other]])):
                    cost = math.dist(pos, coordinates[other])
                    anchor_edges.setdefault(node, []).append((other, cost, "copper"))
                    anchor_edges.setdefault(other, []).append((node, cost, "copper"))
    for i, a in enumerate(specials):
        for j, b in enumerate(specials[:i]):
            # Only add genuine continuous copper corridors, never inferred
            # straight connections between disconnected islands.
            if core.covers(LineString([a, b])):
                cost = math.dist(a, b)
                anchor_edges.setdefault(count+i, []).append((count+j, cost, "copper"))
                anchor_edges.setdefault(count+j, []).append((count+i, cost, "copper"))
    wire_links = {}
    for index, row in enumerate(wires):
        a, b = count + 2 + index * 2, count + 3 + index * 2
        wire_links[a] = [(b, row["length_mm"], "wire:" + row["ref"])]
        wire_links[b] = [(a, row["length_mm"], "wire:" + row["ref"])]
    def point(node):
        return coordinates[node].tolist() if node < count else specials[node - count]
    edge_clear = {}
    def search(include_wires):
        start, end = count, count + 1
        dist, prev, incoming = {start: 0.0}, {}, {}
        heap = [(math.dist(source, target), 0.0, start)]
        visits = 0
        while heap:
            _, cost, node = heapq.heappop(heap)
            if cost > dist[node] + 1e-9: continue
            if node == end: break
            visits += 1
            if visits > 100000: return {"found": False, "reason": "bounded search limit", "visited": visits}
            neighbors = list(anchor_edges.get(node, []))
            if include_wires: neighbors.extend(wire_links.get(node, []))
            if node < count:
                ix, iy = node % nx, node // nx
                for dx, dy in [(1,0),(0,1),(-1,0),(0,-1),(1,1),(-1,1),(-1,-1),(1,-1)]:
                    jx, jy = ix + dx, iy + dy
                    if not 0 <= jx < nx or not 0 <= jy < ny: continue
                    other = jy * nx + jx
                    if not allowed[other]: continue
                    pair = min(node, other), max(node, other)
                    if pair not in edge_clear:
                        edge_clear[pair] = core.covers(LineString([coordinates[node], coordinates[other]]))
                    if edge_clear[pair]: neighbors.append((other, grid * math.hypot(dx,dy), "copper"))
            for other, edgecost, kind in neighbors:
                candidate = cost + edgecost
                if candidate < dist.get(other, math.inf) - 1e-9:
                    dist[other], prev[other], incoming[other] = candidate, node, kind
                    heapq.heappush(heap, (candidate + math.dist(point(other), target), candidate, other))
        if end not in dist: return {"found": False, "reason": "no sampled corridor path", "visited": visits}
        nodes, kinds = [end], []
        while nodes[-1] != start:
            kinds.append(incoming[nodes[-1]])
            nodes.append(prev[nodes[-1]])
        nodes.reverse(); kinds.reverse()
        points = [point(node) for node in nodes]
        compressed = [points[0]]
        compressed_kinds = []
        for i, (pos, kind) in enumerate(zip(points[1:], kinds)):
            if len(compressed) >= 2 and compressed_kinds[-1] == kind:
                a,b=compressed[-2],compressed[-1]
                u=(b[0]-a[0],b[1]-a[1]);v=(pos[0]-b[0],pos[1]-b[1])
                if abs(u[0]*v[1]-u[1]*v[0])<1e-8 and u[0]*v[0]+u[1]*v[1]>=0:
                    compressed[-1]=pos
                    continue
            compressed.append(pos); compressed_kinds.append(kind)
        return {"found": True, "length_mm": dist[end], "polyline_mm": compressed,
                "segment_types": compressed_kinds, "used_wires": sorted(set(kind[5:] for kind in kinds if kind.startswith("wire:"))), "visited": visits}
    return {"source": "C6.2", "target": "U1.11", "grid_mm": grid, "actual_track_endpoint_auxiliary_nodes": len(specials)-track_start, "copper_corridor_radius_mm": radius,
            "straight_distance_mm": math.dist(source,target), "with_native_wires": search(True), "without_native_wires": search(False),
            "scope": "Geometric accessible-route length only; not inductance/current distribution. Copper pad holes are not subtracted; LUT production tolerance is not modeled."}


def exact_track_path(data, net, source, target):
    """Shortest centerline route on actual tracks, with same-pad joins.

    Uses actual segment vertices/intersections rather than resampling to a grid.
    This is a geometric length, not an estimate of HF current distribution.
    """
    import heapq
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import unary_union
    import shapely as s
    pads = [p for p in data["pads"] if p["net"] == net]
    source_pad = next(p for p in pads if f"{p['ref']}.{p['pin']}" == source)
    target_pad = next(p for p in pads if f"{p['ref']}.{p['pin']}" == target)
    segments = [LineString([t["a"],t["b"]]) for t in data["tracks"] if t["net"] == net]
    split = unary_union(segments)
    lines = list(split.geoms) if hasattr(split, "geoms") else [split]
    positions = {tuple(source_pad["position"]), tuple(target_pad["position"])}
    for line in lines: positions.update(tuple(p) for p in line.coords)
    positions = sorted(positions)
    ids = {p:i for i,p in enumerate(positions)}
    edges = {i:{} for i in range(len(positions))}
    def edge(a,b):
        distance = math.dist(positions[a],positions[b])
        edges[a][b] = min(distance,edges[a].get(b, math.inf))
        edges[b][a] = min(distance,edges[b].get(a, math.inf))
    for line in lines:
        on_line = sorted((line.project(Point(p)),i) for i,p in enumerate(positions) if line.distance(Point(p)) < 1e-7)
        for (_,a),(_,b) in zip(on_line,on_line[1:]): edge(a,b)
    for pad in pads:
        copper = unary_union([s.make_valid(Polygon(p["outer"],p["holes"])) for p in pad["copper"]])
        nodes = [i for i,p in enumerate(positions) if copper.covers(Point(p))]
        for a in nodes:
            for b in nodes:
                if a < b and copper.covers(LineString([positions[a],positions[b]])): edge(a,b)
    start,end = ids[tuple(source_pad["position"])],ids[tuple(target_pad["position"])]
    dist,prev,queue = {start:0.0},{},[(0.0,start)]
    while queue:
        cost,node = heapq.heappop(queue)
        if cost > dist[node]+1e-9: continue
        if node == end: break
        for other,length in edges[node].items():
            candidate = cost+length
            if candidate < dist.get(other,math.inf)-1e-9:
                dist[other],prev[other] = candidate,node
                heapq.heappush(queue,(candidate,other))
    result = {"net":net,"source":source,"target":target,"scope":"Actual track centerlines and same-pad copper joins only; no zone shortcut, no inductance or measured EMI claim."}
    if end not in dist: return dict(result,found=False)
    nodes = [end]
    while nodes[-1] != start: nodes.append(prev[nodes[-1]])
    return dict(result,found=True,length_mm=dist[end],polyline_mm=[positions[i] for i in reversed(nodes)])

def final_analysis():
    sys.path.insert(0, str(WORK / "deps"))
    import shapely as s
    from shapely.geometry import Polygon, Point, LineString
    from shapely.ops import unary_union
    data = json.loads((OUT / "geometry.json").read_text())
    def parts(g):
        if g.geom_type == "Polygon": return [g]
        return [p for item in getattr(g, "geoms", []) for p in parts(item)]
    def shape(records):
        return unary_union([poly for record in records for poly in parts(s.make_valid(Polygon(record["outer"], record["holes"])))])
    padrows = [pad for pad in data["pads"] if pad["net"] == "AGND"]
    ground = unary_union([shape(data["zone_polygons"])] + [shape(pad["copper"]) for pad in padrows]
                         + [LineString([t["a"], t["b"]]).buffer(t["width"] / 2, quad_segs=32) for t in data["tracks"] if t["net"] == "AGND"])
    components = sorted(parts(ground), key=lambda poly: -poly.area)
    core = ground.buffer(-.499, quad_segs=32)
    cores = sorted(parts(core), key=lambda poly: -poly.area)
    def find_area(pos, areas):
        return [i for i, area in enumerate(areas) if area.covers(Point(pos))]
    membership = [{"ref": pad["ref"], "pin": pad["pin"], "at": pad["position"],
                   "copper_component": find_area(pad["position"], components),
                   "core_0_998mm_component": find_area(pad["position"], cores)} for pad in padrows]
    native = {fp["ref"] for fp in data["footprints"] if fp.get("native_jumper")}
    wire_edges = []
    for ref in sorted(native):
        endpoints = [row for row in membership if row["ref"] == ref]
        if len(endpoints) == 2:
            wire_edges.append({"ref": ref, "a": endpoints[0], "b": endpoints[1],
                               "length_mm": math.dist(endpoints[0]["at"], endpoints[1]["at"])})
    def graph_groups(field, count):
        parent = list(range(count))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for wire in wire_edges:
            for a in wire["a"][field]:
                for b in wire["b"][field]: parent[find(b)] = find(a)
        groups = {}
        missing = []
        for row in membership:
            label = f"{row['ref']}.{row['pin']}@{row['at']}"
            if not row[field]: missing.append(label)
            else: groups.setdefault(find(row[field][0]), []).append(label)
        return list(groups.values()), missing
    copper_groups, missing = graph_groups("copper_component", len(components))
    core_groups, core_missing = graph_groups("core_0_998mm_component", len(cores))
    return_paths = estimate_return_paths(ground, wire_edges, membership, [t for t in data["tracks"] if t["net"] == "AGND"])
    bypass_paths = {"supply":exact_track_path(data,"V_A","C6.1","U1.4"),
                    "return":exact_track_path(data,"AGND","C6.2","U1.11")}
    if all(p["found"] for p in bypass_paths.values()):
        bypass_paths["total_track_centerline_length_mm"] = sum(p["length_mm"] for p in bypass_paths.values())
    info = {"return_paths": return_paths, "bypass_track_paths":bypass_paths,"board_sha256": data["board_sha256"], "zone_outline_count": len(data["zone_polygons"]),
            "copper_component_count": len(components), "ground_membership": membership,
            "native_ground_wire_edges": wire_edges,
            "redundant_native_wires_with_existing_copper_unchanged": [wire["ref"] for wire in wire_edges if set(wire["a"]["core_0_998mm_component"]) & set(wire["b"]["core_0_998mm_component"])],
            "electrical_ground_groups_with_native_jumpers": copper_groups,
            "missing_ground_pad_centres": missing, "core_0_998mm_component_count": len(cores),
            "ground_groups_after_0_499mm_erosion_with_native_jumpers": core_groups,
            "ground_pad_centres_missing_from_eroded_core": core_missing,
            "scope": "Read-only final filled CAD. Ground copper includes filled zones, AGND pad polygons and AGND track capsules. Native duplicate-number jumper flags supply real wire edges. Erosion screen at 0.998 mm excludes drill-annulus analysis and is not physical validation."}
    (OUT / "final-ground-graph.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    lines = ["# Итоговая геометрическая проверка AGND", "", f"PCB SHA256: `{data['board_sha256']}`.",
             "Снимок заполненной платы сохранён как source-candidate.kicad_pcb; SHA проверен до/после экспорта. CAD root не изменялся.", "",
             f"Контуров заливки AGND: {len(data['zone_polygons'])}; геометрических компонентов всей меди AGND: {len(components)}.",
             f"После native AGND jumpers {', '.join(w['ref'] for w in wire_edges)} все площадки AGND образуют {len(copper_groups)} электрическую группу; пропущенных центров: {len(missing)}.",
             f"После морфологического сужения меди на 0,499 мм + тех же jumper-связей группы площадок: {len(core_groups)}; не попавших в ядро центров: {len(core_missing)}.", ""]
    for wire in wire_edges: lines.append(f"- {wire['ref']}: {wire['a']['at']} → {wire['b']['at']}, {wire['length_mm']:.2f} мм; native jumper прочитан из KiCad.")
    lines += ["", "Избыточные native ground wire edges при неизменной текущей меди: " + str(info["redundant_native_wires_with_existing_copper_unchanged"]),
              f"Кратчайший найденный по сетке 0,5 мм с узлами реальных дорожек геометрический путь C6.2 → U1.11: {return_paths['with_native_wires'].get('length_mm', float('nan')):.2f} мм при прямом расстоянии {return_paths['straight_distance_mm']:.2f} мм. Без native-проводов: {return_paths['without_native_wires'].get('length_mm', float('nan')):.2f} мм. Использованные провода: {return_paths['with_native_wires'].get('used_wires', [])}. Полилиния и параметры — в JSON. Это оценка длины доступного пути, не расчёт распределения ВЧ-тока или индуктивности.",
              f"Отдельная проверка по осевым линиям фактических дорожек: C6.1 → U1.4 (V_A) {bypass_paths['supply'].get('length_mm',float('nan')):.2f} мм; C6.2 → U1.11 (AGND) {bypass_paths['return'].get('length_mm',float('nan')):.2f} мм. Суммарная геометрическая длина двух ветвей {bypass_paths.get('total_track_centerline_length_mm',float('nan')):.2f} мм. Это не длина пути внутри корпуса и не расчёт индуктивности контура.",
              "В geometry.json сохранены исходные контуры и отверстия, эффективная медь площадок, дорожки и Courtyard. final-ground-graph.json содержит принадлежность каждой площадки и граф электрических связей.",
              "Морфологическая проверка ищет потерю связности при ширине около 1 мм. Она не учитывает отверстия внутри контактных колец, реальные погрешности ЛУТ и не удостоверяет аналоговую полосу или защиту. Старый analysis.md с 13 островами был снят во время генерации без заливки и не является итоговым свидетельством."]
    (OUT / "final-ground-graph.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # A local engineering view of the two bypass branches; it is not a LUT
    # printing master and does not replace KiCad's manufacturing plots.
    def svg_polygon(poly):
        rings = [poly.exterior] + list(poly.interiors)
        return " ".join("M " + " L ".join(f"{x:.4f},{y:.4f}" for x,y in ring.coords) + " Z" for ring in rings)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="70 36 40 40" width="900" height="900">',
           '<rect x="70" y="36" width="40" height="40" fill="#ffffff"/>',
           f'<title>C6 bypass geometry, PCB SHA256 {data["board_sha256"]}</title>',
           '<g fill="#c9e3cd" stroke="#91ac96" stroke-width="0.05" fill-rule="evenodd">']
    svg.extend(f'<path d="{svg_polygon(poly)}"/>' for poly in parts(ground))
    svg.append('</g>')
    for track in data["tracks"]:
        if track['net'] != 'AGND':
            a,b=track['a'],track['b']
            svg.append(f'<path d="M {a[0]} {a[1]} L {b[0]} {b[1]}" fill="none" stroke="#d8d5cd" stroke-width="{track["width"]}" stroke-linecap="round"/>')
    for fp in data["footprints"]:
        if fp["top_courtyard"]:
            for poly in parts(shape(fp["top_courtyard"])):
                svg.append(f'<path d="{svg_polygon(poly)}" fill="none" stroke="#777" stroke-width="0.07" stroke-dasharray="0.4 0.3"/>')
    for pad in data["pads"]:
        for poly in parts(shape(pad["copper"])):
            svg.append(f'<path d="{svg_polygon(poly)}" fill="#b4b4b4" stroke="#666" stroke-width="0.05"/>')
        x,y=pad["position"]
        if pad['drill'][0] > 0:
            svg.append(f'<ellipse cx="{x}" cy="{y}" rx="{pad["drill"][0]/2}" ry="{pad["drill"][1]/2}" fill="white"/>')
    for name,color in [('supply','#e87516'),('return','#0785b8')]:
        path=bypass_paths[name]
        if path['found']:
            d='M '+' L '.join(f'{x},{y}' for x,y in path['polyline_mm'])
            svg.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="0.35" stroke-linecap="round" stroke-linejoin="round"/>')
    svg.extend(['<g font-family="sans-serif" font-size="1.1" fill="#202020">',
                '<text x="71" y="37.5">C6: actual B.Cu branch centerlines</text>',
                f'<text x="71" y="39">V_A {bypass_paths["supply"].get("length_mm",math.nan):.2f} mm / AGND {bypass_paths["return"].get("length_mm",math.nan):.2f} mm</text>',
                '<text x="86.5" y="48">U1 adapter</text><text x="88" y="67">C6</text>',
                '<text x="71" y="74">Geometry only; not an EMI or inductance result.</text>',
                f'<text x="71" y="75.5">SHA256 {data["board_sha256"][:16]}...</text>',
                '</g></svg>'])
    (OUT / 'return-path.svg').write_text('\n'.join(svg),encoding='utf-8')
    print(json.dumps({key: info[key] for key in ["board_sha256", "zone_outline_count", "copper_component_count", "electrical_ground_groups_with_native_jumpers", "ground_groups_after_0_499mm_erosion_with_native_jumpers", "ground_pad_centres_missing_from_eroded_core"]}), flush=True)


if __name__ == "__main__":
    final_analysis() if "--final-analyze" in sys.argv else (analyze() if "--analyze" in sys.argv else export_geometry())
