"""Ablation: each component switched off in turn, at each budget.

python ablate.py --items data/items.json --key data/visible_key.json --runs 1

Writes results/ablation.md (the table), results/ablation.json (every number),
and each arm's answers and raw model replies under results/runs/.
"""
import argparse
import importlib.util
import json
import statistics
from pathlib import Path

import pipeline

ARMS = {
    "full system":        {},
    "no prefilter":       {"prefilter": False},
    "no examples":        {"examples": False},
    "no noise rules":     {"noise_rules": False},
    "no vote":            {"vote": False},
    "no plausibility":    {"plausibility": False},
    "direct (no harness)": {"direct": True},
}
# voting and the plausibility check only act when there is more than one sample
ONLY_MULTI = {"no vote", "no plausibility"}
# the direct baseline makes one call however large the budget
ONLY_1X = {"direct (no harness)"}


def load_scorer(path):
    spec = importlib.util.spec_from_file_location("scorer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="data/items.json")
    ap.add_argument("--key", default="data/visible_key.json")
    ap.add_argument("--scorer", default="data/score.py")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--budgets", default="1x,3x,10x")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    from llm import call
    score = load_scorer(a.scorer)
    items = json.loads(Path(a.items).read_text(encoding="utf-8"))
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    out_dir = Path("results")
    (out_dir / "runs").mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "ablation.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else {}

    for arm in a.arms.split(","):
        for budget in a.budgets.split(","):
            if arm in ONLY_MULTI and budget == "1x":
                continue
            if arm in ONLY_1X and budget != "1x":
                continue
            cfg = dict(pipeline.DEFAULT_CFG, **ARMS[arm])
            runs = []
            for r in range(a.runs):
                answers, log = pipeline.run(items, budget, cfg, call, a.workers)
                s = score(key, answers, items)
                tag = f"{arm.replace(' ', '_').replace('(', '').replace(')', '')}_{budget}_run{r}"
                (out_dir / "runs" / f"{tag}_answers.json").write_text(json.dumps(answers, indent=1))
                with open(out_dir / "runs" / f"{tag}_log.jsonl", "w", encoding="utf-8") as f:
                    for row in log:
                        f.write(json.dumps(row) + "\n")
                runs.append({"macro": s["macro_exact_match"], "per_case": s["per_case_rate"],
                             "confusion": s["confusion"]})
                print(f"{arm:22s} {budget:4s} run {r}: macro {s['macro_exact_match']:.3f} {s['per_case_rate']}")
            results.setdefault(arm, {})[budget] = runs
            results_path.write_text(json.dumps(results, indent=1))

    # the table
    budgets = ["1x", "3x", "10x"]
    rows = ["| component | " + " | ".join(budgets) + " |", "|---|" + "---|" * len(budgets)]
    for arm in ARMS:
        cells = []
        for b in budgets:
            runs = results.get(arm, {}).get(b)
            if not runs:
                cells.append("n/a")
                continue
            ms = [x["macro"] * 100 for x in runs]
            sd = f" ± {statistics.stdev(ms):.1f}" if len(ms) > 1 else ""
            cells.append(f"{statistics.mean(ms):.1f}{sd} (n={len(ms)})")
        rows.append(f"| {arm} | " + " | ".join(cells) + " |")
    (out_dir / "ablation.md").write_text("\n".join(rows) + "\n")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
