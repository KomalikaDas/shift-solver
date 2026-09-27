"""Re-run the symbolic half of the pipeline on saved model replies (DEV ONLY).

python dev/replay.py results/v2_1x_log.jsonl [--no-grounding] [--no-last-answer] ...

No API calls. The model's saved replies are fed back in the order they were
made, so any change to parsing, grounding, voting or the solver can be measured
on exactly the same model outputs. Prompt changes can NOT be tested this way,
since the model would have answered a different prompt.
"""
import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pipeline

ap = argparse.ArgumentParser()
ap.add_argument("log")
for name in ("prefilter", "grounding", "last-answer", "disjunction", "vote", "plausibility"):
    ap.add_argument(f"--no-{name}", action="store_true")
a = ap.parse_args()

replies = defaultdict(list)
for line in open(a.log, encoding="utf-8"):
    row = json.loads(line)
    if "reply" in row:
        replies[row["id"]].append((row["call"], row["reply"]))
queue = {k: [r for _, r in sorted(v)] for k, v in replies.items()}
n = max(len(v) for v in queue.values())
budget = {1: "1x", 3: "3x"}.get(n, "10x")


def replay_call(item_id, messages):
    if not queue.get(item_id):
        raise RuntimeError("no saved reply left")
    return queue[item_id].pop(0)


cfg = dict(pipeline.DEFAULT_CFG)
for name in ("prefilter", "grounding", "last_answer", "disjunction", "vote", "plausibility"):
    if getattr(a, "no_" + name):
        cfg[name] = False
items = json.loads((ROOT / "data/items.json").read_text(encoding="utf-8"))
answers, _ = pipeline.run(items, budget, cfg, replay_call, workers=1)

spec = importlib.util.spec_from_file_location("scorer", ROOT / "data/score.py")
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)
key = json.loads((ROOT / "data/visible_key.json").read_text(encoding="utf-8"))
s = scorer.score(key, answers, items)
print(f"replayed {a.log} as {budget} with {cfg}")
print("macro:", s["macro_exact_match"], s["per_case_rate"])
for true_case, row in s["confusion"].items():
    print(f"  true {true_case:12s} -> {row}")
