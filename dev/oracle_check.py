"""Solver ceiling check: perfect extraction (template oracle) -> solver -> score.

python dev/oracle_check.py
No model calls. Shows that everything after extraction is exact, so every
error in the real system comes from the model's reading of the lines.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev"))
import solver
import template_oracle as oracle

TAKEOVER = {"TAKEOVER": lambda m: {"type": "before", "a": m[2], "b": m[1]}}


def to_tuple(c):
    term = lambda x: x["station"] if isinstance(x, dict) else x
    t = c["type"]
    if t == "at": return ("AT", c["person"], c["block"])
    if t == "not_at": return ("NOT_AT", c["person"], c["block"])
    if t == "station": return ("ON", c["person"], c["station"])
    if t == "not_station": return ("NOT_ON", c["person"], c["station"])
    if t == "before": return ("BEFORE", term(c["a"]), term(c["b"]))
    if t == "right_before": return ("NEXT", term(c["a"]), term(c["b"]))
    if t == "between":
        return ("BETWEEN", term(c["mid"])) + tuple(sorted((term(c["a"]), term(c["b"]))))


def main():
    items = json.loads((ROOT / "data/items.json").read_text(encoding="utf-8"))
    key = json.loads((ROOT / "data/visible_key.json").read_text(encoding="utf-8"))
    answers = {}
    for it in items:
        h = solver.parse_header(it["text"])
        lines = solver.body_lines(it["text"])
        readings = {}
        for i, l in enumerate(lines):
            c = oracle.extract(l, TAKEOVER)
            readings[i] = [to_tuple(c)] if c else []
        sols = solver.solutions(h, readings)
        if len(sols) == 1:
            answers[it["id"]] = {"case": "unique", "assignment": solver.to_assignment(sols[0], h)}
        elif sols:
            answers[it["id"]] = {"case": "ambiguous", "assignments": [solver.to_assignment(w, h) for w in sols]}
        else:
            core = solver.minimal_conflict(h, readings)
            answers[it["id"]] = {"case": "inconsistent", "conflicts": [lines[i] for i in sorted(core)]}

    spec = importlib.util.spec_from_file_location("scorer", ROOT / "data/score.py")
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    s = scorer.score(key, answers, items)
    print("solver ceiling with perfect extraction:", s["macro_exact_match"], s["per_case_rate"])


if __name__ == "__main__":
    main()
