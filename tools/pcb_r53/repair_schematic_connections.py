"""Restore explicit pin/T junctions in a copied schematic, then require ERC/parity.

Only existing on-line contact points are joined. Bare X crossings are not joined.
This geometry transformation is not an electrical design authority: the output
must be compared with the accepted pin-net partition before use.
"""
from pathlib import Path
import json
import math
import re
import sys
import uuid


def parse(text):
    stack, spans, starts = [], {}, []
    root = None
    for match in re.finditer(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', text):
        token = match.group()
        if token == '(':
            node = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            starts.append(match.start())
        elif token == ')':
            node = stack.pop()
            spans[id(node)] = (starts.pop(), match.end())
            if not stack:
                root = node
        else:
            stack[-1].append(json.loads(token) if token.startswith('"') else token)
    return root, spans


def children(node, key):
    return [v for v in node if isinstance(v, list) and v and v[0] == key]


def child(node, key):
    return next(iter(children(node, key)), None)


def point(node):
    return tuple(round(float(v) * 1_000_000) for v in node[1:3])


def on_segment(p, a, b):
    return ((p[0]-a[0])*(b[1]-a[1]) == (p[1]-a[1])*(b[0]-a[0])
            and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def pins_absolute(root):
    libraries = {v[1]: v for v in children(child(root, 'lib_symbols'), 'symbol')}
    result = []
    for symbol in children(root, 'symbol'):
        library = libraries[child(symbol, 'lib_id')[1]]
        unit = int(child(symbol, 'unit')[1])
        at = child(symbol, 'at')
        origin = point(at)
        angle = math.radians(float(at[3]))
        mirror = child(symbol, 'mirror')
        ref = next(v[2] for v in children(symbol, 'property') if v[1] == 'Reference')
        # Library pins are in Cartesian coordinates, schematic Y points down.
        body_pins = list(children(library, 'pin'))
        for body in children(library, 'symbol'):
            body_unit = int(body[1].rsplit('_', 2)[-2])
            if body_unit in (0, unit):
                body_pins.extend(children(body, 'pin'))
        for pin in body_pins:
            x, y = point(child(pin, 'at'))
            if mirror:
                if mirror[1] == 'x':
                    y = -y
                elif mirror[1] == 'y':
                    x = -x
                else:
                    raise ValueError('Unsupported mirror')
            px = origin[0] + round(x * math.cos(angle) - y * math.sin(angle))
            py = origin[1] - round(x * math.sin(angle) + y * math.cos(angle))
            result.append((ref, child(pin, 'number')[1], (px, py)))
    return result


def fmt(value):
    return f'{value / 1_000_000:.6f}'.rstrip('0').rstrip('.')


def main(source, output):
    text = source.read_text('utf-8')
    root, spans = parse(text)
    wires = [(v, *(point(p) for p in children(child(v, 'pts'), 'xy')))
             for v in children(root, 'wire')]
    pins = pins_absolute(root)
    old_junctions = {point(child(v, 'at')): v for v in children(root, 'junction')}
    points = {p for _, a, b in wires for p in (a, b)}
    points.update(p for _, _, p in pins)
    points.update(old_junctions)
    edits, segments, split_records = [], [], []
    for node, a, b in wires:
        contacts = sorted((p for p in points if on_segment(p, a, b)),
                          key=lambda p: (p[0]-a[0])**2 + (p[1]-a[1])**2)
        segments.extend(zip(contacts, contacts[1:]))
        if len(contacts) > 2:
            start, end = spans[id(node)]
            rendered = []
            for index, (first, last) in enumerate(zip(contacts, contacts[1:])):
                # Preserve stroke/settings; only coordinates and split UUID change.
                wire_text = text[start:end]
                wire_text = re.sub(r'\(pts\s*\(xy\s+[^)]+\)\s*\(xy\s+[^)]+\)\s*\)',
                                  f'(pts (xy {fmt(first[0])} {fmt(first[1])}) '
                                  f'(xy {fmt(last[0])} {fmt(last[1])}))', wire_text)
                if index:
                    wire_text = re.sub(r'\(uuid\s+"[^"]+"\)', f'(uuid "{uuid.uuid4()}")', wire_text)
                rendered.append(wire_text)
            edits.append((start, end, '\n\t'.join(rendered)))
            split_records.append({'original': [list(a), list(b)], 'contacts': [list(p) for p in contacts]})
    additions = []
    for p in points:
        arms = sum(p in (a, b) for a, b in segments)
        pin_count = sum(position == p for _, _, position in pins)
        if p not in old_junctions and arms >= 2 and arms + pin_count >= 3:
            additions.append(p)
    appended = '\n'.join(
        f'\t(junction (at {fmt(p[0])} {fmt(p[1])}) (diameter 0) '
        f'(color 0 0 0 0) (uuid "{uuid.uuid4()}"))' for p in sorted(additions))
    end_of_root = spans[id(root)][1] - 1
    edits.append((end_of_root, end_of_root, '\n' + appended + '\n'))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, 'utf-8')
    report = {'source': str(source), 'output': str(output), 'wires_before': len(wires),
              'wires_after': len(segments), 'pin_count': len(pins),
              'junctions_before': len(old_junctions), 'junctions_added': len(additions),
              'added_junctions_mm': [[v / 1_000_000 for v in p] for p in sorted(additions)],
              'split_records_internal_nm': split_records,
              'no_bare_crossings_joined': True}
    output.with_suffix('.repair.json').write_text(json.dumps(report, indent=2) + '\n', 'utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ['added_junctions_mm', 'split_records_internal_nm']}))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
