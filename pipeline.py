"""Entry point: python pipeline.py <items.json> --budget 1x --out answers.json

Per item:
  1. read the header symbolically (names, blocks, stations)
  2. prefilter: lines that mention no person, block or station go straight to NONE
  3. ask the model to translate each remaining line into the constraint language
  4. validate the model's output against the header vocabulary
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
def _term(tok, h):
    """Map a token to a canonical person or station, or None."""
    t = tok.strip(" ,.;:'\"()<>[]")
    t = re.sub(r"'s$", "", t)
    for p in h["staff"]:
        if t.lower() == p.lower():
            return p
    for s in h["stations"]:
        if t.lower() == s.lower():
            return s
    return None


def parse_reading(text, h):
    """One constraint string -> list of valid constraint tuples."""
    out = []
    for piece in text.split(";"):
        toks = piece.split()
        if not toks:
            continue
        op = toks[0].upper().strip(":,")
        if op not in OPS:
            continue
        args = toks[1:]
        if op in ("AT", "NOT_AT"):
            if len(args) < 2:
                continue
            x, blk = _term(args[0], h), solver.norm_time(" ".join(args[1:]))
            if x and blk in h["blocks"]:
                out.append((op, x, blk))
        elif op in ("ON", "NOT_ON"):
            if len(args) < 2:
                continue
            p, s = _term(args[0], h), _term(args[1], h)
            if p in h["staff"] and s in h["stations"]:
                out.append((op, p, s))
        else:
            terms = [_term(a, h) for a in args]
            terms = [t for t in terms if t]
            if len(terms) < OPS[op] or len(set(terms[:OPS[op]])) < OPS[op]:
                continue  # wrong arity or a person related to themselves
            if op == "BETWEEN":
                m, x, y = terms[:3]
                out.append((op, m) + tuple(sorted((x, y))))
            else:
                out.append((op, terms[0], terms[1]))
    return out


def parse_reply(reply, numbered, h):
    """Model reply -> {line_index: [constraints]} for the lines it was shown."""
    wanted = {n: idx for n, idx in numbered}
    readings = {idx: [] for idx in wanted.values()}
    for raw in reply.splitlines():
        m = re.match(r"^\s*\**\s*L?(\d+)\s*[:.)\-]\s*(.*)$", raw)
        if not m or int(m.group(1)) not in wanted:
            continue
        idx = wanted[int(m.group(1))]
        readings[idx] = sorted(set(readings[idx] + parse_reading(m.group(2), h)))
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
    reply = call(item["id"], [{"role": "user", "content": ask}])
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
        samples.append(parse_reply(reply, numbered, h))
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


DEFAULT_CFG = {"prefilter": True, "examples": True, "noise_rules": True,
               "vote": True, "plausibility": True, "direct": False}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("items")
    ap.add_argument("--budget", choices=BUDGETS, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--log", default=None, help="where to save raw model replies (jsonl)")
    for name in ("prefilter", "examples", "noise-rules", "vote", "plausibility"):
        ap.add_argument(f"--no-{name}", action="store_true")
    ap.add_argument("--direct", action="store_true", help="baseline: model answers directly")
    a = ap.parse_args(argv)

    cfg = dict(DEFAULT_CFG)
    for name in ("prefilter", "examples", "noise_rules", "vote", "plausibility"):
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
