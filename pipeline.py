"""Entry point: python pipeline.py <items.json> --budget 1x --out answers.json

Per item:
  1. read the header symbolically (names, blocks, stations)
  2. prefilter: lines that mention no person, block or station go straight to NONE
  3. ask the model to translate each remaining line into the constraint language
  4. validate the model's output: known names only, and grounding (everything
     a constraint mentions must appear in its own line)
  5. at 3x/10x, repeat step 3 and combine the samples (vote + plausibility)
  6. enumerate every rota and decide unique / ambiguous / inconsistent
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import prompt
import solver

BUDGETS = {"1x": 1, "3x": 3, "10x": 10}
OPS = {"AT": 2, "NOT_AT": 2, "ON": 2, "NOT_ON": 2, "BEFORE": 2, "NEXT": 2, "BETWEEN": 3}


# ---------- step 2: prefilter ----------------------------------------------
def mentions_vocab(line, h):
    low = line.lower()
    if any(re.search(r"\b" + re.escape(p) + r"\b", line) for p in h["staff"]):
        return True
    if any(re.search(r"\b" + re.escape(s.lower()) + r"\b", low) for s in h["stations"]):
        return True
    return solver.norm_time(line) is not None


# ---------- step 4: parse and validate one model reply ---------------------
OPS = {"AT", "NOT_AT", "ON", "NOT_ON", "BEFORE", "AFTER",
       "JUST_BEFORE", "JUST_AFTER", "BETWEEN", "NEXT"}


def _term(tok, h):
    """Map a token to a canonical person or station, or None."""
    t = tok.strip(" ,.;:'\"()<>[]*`\u201c\u201d")
    t = re.sub(r"'s$", "", t)
    for p in h["staff"]:
        if t.lower() == p.lower():
            return p
    for s in h["stations"]:
        if t.lower() == s.lower():
            return s
    return None


def _typed(tokens, h):
    """Sort tokens into people, stations and blocks."""
    people, stations, blocks = [], [], []
    for tok in tokens:
        t = _term(tok, h)
        if t in h["staff"]:
            people.append(t)
        elif t in h["stations"]:
            stations.append(t)
        else:
            b = solver.norm_time(tok)
            if b in h["blocks"]:
                blocks.append(b)
    return people, stations, blocks


def _canon(op, subj, args, h, prefix=False):
    """Infix pieces -> one canonical constraint tuple, or None if malformed.
    Type-directed repair: AT/ON are chosen by what the argument IS, so
    'Ayesha NOT_AT calibration' becomes NOT_ON (calibration is a station, not a
    block) and 'NOT_ON calibration Ayesha' is read by type, not position."""
    neg = op.startswith("NOT_")
    if op in ("AT", "NOT_AT", "ON", "NOT_ON"):
        people, stations, blocks = _typed(([subj] if subj else []) + args, h)
        if blocks:
            x = people[0] if people else (stations[0] if stations else None)
            return ("NOT_AT" if neg else "AT", x, blocks[0]) if x else None
        if not (people and stations):
            return None
        # AT given a station is repaired to ON when a person is the subject, or
        # when the keyword came first ('NOT_AT packing Meera'); an infix line
        # with a station subject ('intake AT earlier than Priya') is rejected
        if op in ("AT", "NOT_AT") and not prefix and _term(subj or "", h) not in h["staff"]:
            return None
        return ("NOT_ON" if neg else "ON", people[0], stations[0])
    terms = [t for t in (_term(a, h) for a in args) if t]
    x = _term(subj, h) if subj else None
    if x is None:
        return None
    if op == "BETWEEN":
        if len(terms) < 2 or len({x, terms[0], terms[1]}) < 3:
            return None
        return ("BETWEEN", x) + tuple(sorted(terms[:2]))
    if not terms or terms[0] == x:
        return None
    y = terms[0]
    return {"BEFORE": ("BEFORE", x, y), "AFTER": ("BEFORE", y, x),
            "JUST_BEFORE": ("NEXT", x, y), "JUST_AFTER": ("NEXT", y, x),
            "NEXT": ("NEXT", x, y)}[op]


THINKING = re.compile(r"->|\u2192|\?|\bso\b|\bmeans\b|\bbut\b|\bactually\b", re.I)


def _candidates(text, h):
    """Every well-formed constraint in a piece of text, in order of appearance.
    Keywords must be in capitals, so ordinary words like 'on' or 'at' in the
    model's commentary are never read as constraints."""
    toks = text.replace(",", " ").split()
    clean = [t.strip(":*`.()[]\"'\u201c\u201d") for t in toks]
    out = []
    for pos, word in enumerate(clean):
        if word not in OPS:
            continue
        stop = next((j for j in range(pos + 1, len(clean)) if clean[j] in OPS), len(clean))
        rest = [t for t in toks[pos + 1:stop] if t.lower() != "and"]
        before = [t for t in toks[:pos] if _term(t, h)]
        prefix = not before
        if before:
            subj, args = before[-1], rest
        elif rest:  # prefix fallback: "BETWEEN Samuel Meera Priya"
            subj, args = rest[0], rest[1:]
        else:
            continue
        c = _canon(word, subj, args, h, prefix)
        if c:
            out.append(c)
    return out


def parse_reading(text, h, last_only=True):
    """One reply line -> list of pieces, each piece a list of constraints that
    were joined with ';'. Granite often reasons out loud even with thinking
    disabled, quoting the line and ending with its answer. When the line shows
    that, only the LAST constraint is kept. An echoed note never yields a
    constraint, because keywords must be in capitals and the notes contain none."""
    if last_only and THINKING.search(text):
        found = _candidates(text, h)
        return [found[-1:]] if found else []
    return [p for p in (_candidates(piece, h) for piece in text.split(";")) if p]


def combine_pieces(pieces, h, disjunction=True):
    """Pieces of one line -> constraints for that line.
    Normally the pieces all hold ('A ; B' = both). But a single line in these
    notes never contradicts itself (every real conflict spans 3+ statements),
    so if the pieces clash on their own, the model was listing alternatives:
    'X AFTER A AND X BEFORE B ; X AFTER B AND X BEFORE A' is one OR."""
    flat = [c for p in pieces for c in p]
    if not flat:
        return []
    if solver.solutions(h, {0: flat}):
        return sorted(set(flat))
    if disjunction and len(pieces) > 1:
        alts = [tuple(sorted(set(p))) for p in pieces if solver.solutions(h, {0: p})]
        if len(alts) > 1:
            return [("OR", tuple(sorted(set(alts))))]
        if len(alts) == 1:
            return list(alts[0])
    return []  # the line contradicts itself: the reading is broken, drop it


def grounded(c, line, h):
    """Every person, station and block in the constraint appears in the line."""
    if c[0] == "OR":
        return all(grounded(x, line, h) for alt in c[1] for x in alt)
    low = line.lower()
    for x in c[1:]:
        if x in h["staff"]:
            if not re.search(r"\b" + re.escape(x) + r"\b", line):
                return False
        elif x in h["stations"]:
            if not re.search(r"\b" + re.escape(x.lower()) + r"\b", low):
                return False
        elif x in h["blocks"]:
            if solver.norm_time(x) not in {solver.norm_time(m) for m in
                                           re.findall(r"\d{1,2}:\d{2}", line)}:
                return False
    return True


def parse_reply(reply, numbered, h, lines=None, ground=True, last_only=True, disjunction=True):
    """Model reply -> {line_index: [constraints]} for the lines it was shown.
    If the model answers the same line twice, its last answer counts.
    With ground=True, constraints naming anything absent from their line are dropped."""
    wanted = {n: idx for n, idx in numbered}
    readings = {idx: [] for idx in wanted.values()}
    for raw in reply.splitlines():
        m = re.match(r"^\s*\**\s*L?(\d+)\s*[:.)\-]\s*(.*)$", raw)
        if not m or int(m.group(1)) not in wanted:
            continue
        idx = wanted[int(m.group(1))]
        cs = combine_pieces(parse_reading(m.group(2), h, last_only), h, disjunction)
        if ground and lines is not None:
            cs = [c for c in cs if grounded(c, lines[idx], h)]
        if last_only:
            readings[idx] = cs
        else:
            readings[idx] = sorted(set(readings[idx] + cs))
    return readings


# ---------- step 5: combining samples ---------------------------------------
def outcome(h, readings, worlds):
    sols = solver.solutions(h, readings, worlds)
    core = solver.minimal_conflict(h, readings) if not sols else None
    return sols, core


def plausible(sols, core):
    """The task promises 1 rota, 2-4 rotas, or a conflict of 3+ statements."""
    return (1 <= len(sols) <= 4) or (core is not None and len(core) >= 3)


def combine(samples, h, worlds, cfg):
    if not cfg["vote"]:
        candidates = samples
    else:
        voted = {}
        for idx in samples[0]:
            counts = Counter(tuple(s.get(idx, [])) for s in samples)
            best = max(counts.values())
            # tie: keep the reading from the earliest sample among the leaders
            for s in samples:
                if counts[tuple(s.get(idx, []))] == best:
                    voted[idx] = list(s.get(idx, []))
                    break
        candidates = [voted] + samples
    if cfg["plausibility"]:
        for r in candidates:
            sols, core = outcome(h, r, worlds)
            if plausible(sols, core):
                return r, sols, core
    r = candidates[0]
    sols, core = outcome(h, r, worlds)
    return r, sols, core


# ---------- the direct baseline: model answers the whole item ---------------
def direct_answer(item, h, call):
    ask = (item["text"] + "\n\nWork out the rota. Reply with JSON only, in one of these forms:\n"
           '{"case": "unique", "assignment": {name: {"block": .., "station": ..}}}\n'
           '{"case": "ambiguous", "assignments": [ ... ]}\n'
           '{"case": "inconsistent", "conflicts": ["<statement quoted in full>", ...]}')
    try:
        reply = call(item["id"], [{"role": "user", "content": ask}])
    except Exception as e:  # no retries, as everywhere else
        return {"case": "unique", "assignment": {}}, "ERROR " + repr(e)
    m = re.search(r"\{.*\}", reply, re.S)
    try:
        return json.loads(m.group(0)), reply
    except Exception:
        return {"case": "unique", "assignment": {}}, reply


# ---------- one item ---------------------------------------------------------
def solve_item(item, n_calls, cfg, call, log):
    h = solver.parse_header(item["text"])
    lines = solver.body_lines(item["text"])
    if cfg["direct"]:
        ans, reply = direct_answer(item, h, call)
        log.append({"id": item["id"], "call": 0, "reply": reply})
        return ans

    if cfg["prefilter"]:
        keep = [i for i, l in enumerate(lines) if mentions_vocab(l, h)]
    else:
        keep = list(range(len(lines)))
    numbered = [(n + 1, idx) for n, idx in enumerate(keep)]
    messages = prompt.build(h, [(n, lines[idx]) for n, idx in numbered],
                            examples=cfg["examples"], noise_rules=cfg["noise_rules"])

    samples = []
    for k in range(n_calls):
        try:
            reply = call(item["id"], messages)
        except Exception as e:  # no retries: a retry could break the budget
            log.append({"id": item["id"], "call": k, "error": repr(e)})
            continue
        log.append({"id": item["id"], "call": k, "reply": reply})
        samples.append(parse_reply(reply, numbered, h, lines, cfg["grounding"],
                                   cfg["last_answer"], cfg["disjunction"]))
    if not samples:
        samples = [{idx: [] for _, idx in numbered}]

    worlds = solver.all_worlds(h)
    readings, sols, core = combine(samples, h, worlds, cfg)
    if sols and len(sols) == 1:
        return {"case": "unique", "assignment": solver.to_assignment(sols[0], h)}
    if sols:
        return {"case": "ambiguous", "assignments": [solver.to_assignment(w, h) for w in sols]}
    return {"case": "inconsistent", "conflicts": [lines[i] for i in sorted(core)]}


def run(items, budget, cfg, call, workers=6):
    n_calls = BUDGETS[budget] if cfg["direct"] is False else 1
    if not cfg["vote"] and not cfg["plausibility"]:
        n_calls = 1  # extra samples would be ignored, so don't spend them
    log = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {it["id"]: pool.submit(solve_item, it, n_calls, cfg, call, log) for it in items}
        answers = {iid: f.result() for iid, f in futures.items()}
    return answers, log


def replay_call_from(log_rows):
    """A stand-in for the model that returns saved replies, in the order they
    were made. Lets the symbolic components be ablated on identical outputs."""
    import collections
    q = collections.defaultdict(list)
    for row in sorted((r for r in log_rows if "reply" in r), key=lambda r: r["call"]):
        q[row["id"]].append(row["reply"])

    def call(item_id, messages):
        if not q.get(item_id):
            raise RuntimeError("no saved reply left for " + item_id)
        return q[item_id].pop(0)
    return call


DEFAULT_CFG = {"prefilter": True, "grounding": True, "last_answer": True, "disjunction": True, "examples": True, "noise_rules": True,
               "vote": True, "plausibility": True, "direct": False}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("items")
    ap.add_argument("--budget", choices=BUDGETS, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--log", default=None, help="where to save raw model replies (jsonl)")
    for name in ("prefilter", "grounding", "last-answer", "disjunction", "examples", "noise-rules",
                 "vote", "plausibility"):
        ap.add_argument(f"--no-{name}", action="store_true")
    ap.add_argument("--direct", action="store_true", help="baseline: model answers directly")
    a = ap.parse_args(argv)

    cfg = dict(DEFAULT_CFG)
    for name in ("prefilter", "grounding", "last_answer", "disjunction", "examples", "noise_rules",
                 "vote", "plausibility"):
        if getattr(a, "no_" + name):
            cfg[name] = False
    cfg["direct"] = a.direct

    from llm import call
    items = json.loads(Path(a.items).read_text(encoding="utf-8"))
    t0 = time.time()
    answers, log = run(items, a.budget, cfg, call, a.workers)
    Path(a.out).write_text(json.dumps(answers, indent=1), encoding="utf-8")
    if a.log:
        Path(a.log).parent.mkdir(parents=True, exist_ok=True)
        with open(a.log, "w", encoding="utf-8") as f:
            for row in log:
                f.write(json.dumps(row) + "\n")
    print(f"wrote {len(answers)} answers to {a.out} in {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
