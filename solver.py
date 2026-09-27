"""Symbolic core: reading the header, checking constraints, enumerating rotas,
and finding minimal conflicting sets. No model calls in this file."""
import itertools
import re

TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def norm_time(s):
    m = TIME.search(s)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _names(s):
    s = s.replace(" and ", ", ")
    return [x.strip() for x in s.split(",") if x.strip()]


def parse_header(text):
    head = text.split("\n\n", 1)[0]
    staff = _names(re.search(r"rota:\s*([^.]+)\.", head).group(1))
    blocks = [f"{int(h):02d}:{m}" for h, m in TIME.findall(head)]
    m = re.search(r"one person on each:\s*([^.]+)\.", head) or \
        re.search(r"stations?[^:]*:\s*([^.]+)\.", head)
    stations = _names(m.group(1)) if m else []
    m = re.search(r"people on a station are\s*([^;.]+)", head)
    on = _names(m.group(1)) if m else list(staff)
    return {"staff": staff, "blocks": blocks, "stations": stations, "on_station": on}


def body_lines(text):
    parts = text.split("\n\n", 1)
    body = parts[1] if len(parts) > 1 else ""
    return [l.strip() for l in body.split("\n") if l.strip()]


def all_worlds(h):
    staff, stations, on = h["staff"], h["stations"], h["on_station"]
    out = []
    for bp in itertools.permutations(range(len(h["blocks"])), len(staff)):
        blk = dict(zip(staff, bp))
        for sp in itertools.permutations(stations, len(on)):
            out.append((blk, dict(zip(on, sp))))
    return out


def _pos(term, world, h):
    """Block index of a term: a person, or a station meaning whoever holds it."""
    blk, st = world
    if term in blk:
        return blk[term]
    for person, station in st.items():
        if station == term:
            return blk[person]
    return None


def holds(c, world, h):
    op = c[0]
    blk, st = world
    if op == "OR":  # ("OR", (alt1, alt2, ...)), each alt a tuple of constraints
        return any(all(holds(x, world, h) for x in alt) for alt in c[1])
    if op in ("AT", "NOT_AT"):
        p = _pos(c[1], world, h)
        ok = p is not None and h["blocks"][p] == c[2]
        return ok if op == "AT" else not ok
    if op == "ON":
        return st.get(c[1]) == c[2]
    if op == "NOT_ON":
        return st.get(c[1]) != c[2]
    a = _pos(c[1], world, h)
    b = _pos(c[2], world, h)
    if a is None or b is None:
        return False
    if op == "BEFORE":
        return a < b
    if op == "NEXT":
        return a + 1 == b
    if op == "BETWEEN":
        x = _pos(c[3], world, h)
        return x is not None and min(b, x) < a < max(b, x)
    raise ValueError(op)


def solutions(h, readings, worlds=None):
    """readings: {line_index: [constraint, ...]}. Returns the consistent worlds."""
    worlds = worlds if worlds is not None else all_worlds(h)
    cons = [c for cs in readings.values() for c in cs]
    return [w for w in worlds if all(holds(c, w, h) for c in cons)]


def minimal_conflict(h, readings):
    """Deletion-based minimal unsatisfiable subset, at the level of whole lines.
    Drop each line in turn; if the rest is still contradictory, it was not needed."""
    worlds = all_worlds(h)
    core = [i for i in readings if readings[i]]
    i = 0
    while i < len(core):
        trial = core[:i] + core[i + 1:]
        if not solutions(h, {j: readings[j] for j in trial}, worlds):
            core = trial
        else:
            i += 1
    return core


def to_assignment(world, h):
    blk, st = world
    out = {}
    for p in h["staff"]:
        d = {"block": h["blocks"][blk[p]]}
        if p in st:
            d["station"] = st[p]
        out[p] = d
    return out
