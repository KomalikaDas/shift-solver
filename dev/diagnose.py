"""Line-level error analysis of a run's raw model replies (DEV ONLY).

python dev/diagnose.py results/first_1x_log.jsonl

Compares the model's reading of every line with the template oracle's reading
and groups the errors by sentence pattern, so you can see WHICH kinds of line
the model gets wrong and HOW (invented a constraint, missed one, or got it wrong).
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dev"))
import pipeline
import solver
import template_oracle as oracle
from oracle_check import to_tuple, TAKEOVER


def pattern(line, h):
    s = oracle.strip(line)
    for p in h["staff"]:
        s = re.sub(r"\b" + p + r"\b", "P", s)
    for st in h["stations"]:
        s = re.sub(r"\b" + st + r"\b", "S", s, flags=re.I)
    return re.sub(r"\d{1,2}:\d{2}", "T", s)


items = {it["id"]: it for it in json.loads((ROOT / "data/items.json").read_text(encoding="utf-8"))}
log_path = sys.argv[1]
rows = [json.loads(l) for l in open(log_path, encoding="utf-8")]

kinds = Counter()
by_pattern = defaultdict(Counter)
examples = defaultdict(list)
total = 0
for row in rows:
    if "reply" not in row or row["id"] not in items:
        continue
    it = items[row["id"]]
    h = solver.parse_header(it["text"])
    lines = solver.body_lines(it["text"])
    keep = [i for i, l in enumerate(lines) if pipeline.mentions_vocab(l, h)]
    numbered = [(n + 1, idx) for n, idx in enumerate(keep)]
    got = pipeline.parse_reply(row["reply"], numbered, h)
    for _, idx in numbered:
        c = oracle.extract(lines[idx], TAKEOVER)
        truth = sorted([to_tuple(c)]) if c else []
        mine = sorted(got.get(idx, []))
        total += 1
        if mine == truth:
            kinds["correct"] += 1
            continue
        if not truth:
            kind = "INVENTED (noise read as a constraint)"
        elif not mine:
            kind = "MISSED (real constraint read as NONE)"
        else:
            kind = "WRONG (real constraint, wrong translation)"
        kinds[kind] += 1
        pat = pattern(lines[idx], h)
        by_pattern[kind][pat] += 1
        if len(examples[pat]) < 2:
            examples[pat].append(f"{lines[idx]}\n        truth: {truth}\n        model: {mine}")

print(f"lines checked: {total}")
for k, v in kinds.most_common():
    print(f"  {k}: {v} ({100 * v / total:.1f}%)")
for kind in by_pattern:
    print(f"\n=== {kind} -- top patterns ===")
    for pat, n in by_pattern[kind].most_common(8):
        print(f"{n:3d}  {pat}")
        for e in examples[pat][:1]:
            print(f"      e.g. {e}")
