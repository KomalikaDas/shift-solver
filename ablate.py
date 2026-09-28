"""Ablation: each component switched off in turn, at each budget.

python ablate.py                      # everything (about 3,400 model calls)
python ablate.py --budgets 1x         # just the 1x column
python ablate.py --runs 3             # repeat each live run to see the spread
python ablate.py --out-dir results_kaggle   # keep one backend's numbers apart

Two kinds of component, measured two ways:
- PROMPT components (prefilter, worked example, noise rules) change what the
  model is asked, so each "without" arm is a fresh live run.
- SYMBOLIC components (grounding, last-answer parsing, disjunctions, voting,
  plausibility) only change what happens to the model's replies. Their
  "without" arms REPLAY the full system's own saved replies, so the with/without
  difference is measured on identical model outputs, with no sampling noise
  between the two, and no extra calls.

Writes results/ablation.md (the table) and results/ablation.json (every number),
plus each run's answers and raw replies under results/runs/.
"""
import argparse
import importlib.util
import json
import statistics
from pathlib import Path

import pipeline

LIVE_ARMS = {
    "full system":          {},
    "with prefilter":       {"prefilter": True},   # built, then removed
    "no worked example":    {"examples": False},
    "no noise rules":       {"noise_rules": False},
    "direct (no harness)":  {"direct": True},
}
REPLAY_ARMS = {
    "no grounding":         {"grounding": False},
    "no last-answer parse": {"last_answer": False},
    "no disjunction":       {"disjunction": False},
    "no vote":              {"vote": False},
    "no plausibility":      {"plausibility": False},
}
ONLY_MULTI = {"no vote", "no plausibility"}   # these only act with 2+ samples
ONLY_1X = {"direct (no harness)"}             # one call whatever the budget
ORDER = list(LIVE_ARMS)[:1] + list(REPLAY_ARMS) + list(LIVE_ARMS)[1:]


def load_scorer(path):
    spec = importlib.util.spec_from_file_location("scorer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.score


def tag(arm, budget, r):
    return "".join(ch if ch.isalnum() else "_" for ch in arm) + f"_{budget}_run{r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="data/items.json")
    ap.add_argument("--key", default="data/visible_key.json")
    ap.add_argument("--scorer", default="data/score.py")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--budgets", default="1x,3x,10x")
    ap.add_argument("--arms", default=",".join(ORDER))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out-dir", default="results",
                    help="where the table, numbers and run files go")
    a = ap.parse_args()

    from llm import call
    score = load_scorer(a.scorer)
    items = json.loads(Path(a.items).read_text(encoding="utf-8"))
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    out = Path(a.out_dir)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    res_path = out / "ablation.json"
    results = json.loads(res_path.read_text()) if res_path.exists() else {}
    wanted = a.arms.split(",")

    def record(arm, budget, r, answers, log):
        t = tag(arm, budget, r)
        (out / "runs" / f"{t}_answers.json").write_text(json.dumps(answers, indent=1))
        if log is not None:
            with open(out / "runs" / f"{t}_log.jsonl", "w", encoding="utf-8") as f:
                for row in log:
                    f.write(json.dumps(row) + "\n")
        s = score(key, answers, items)
        entry = {"macro": s["macro_exact_match"], "per_case": s["per_case_rate"],
                 "confusion": s["confusion"]}
        runs = results.setdefault(arm, {}).setdefault(budget, [])
        if r < len(runs):
            runs[r] = entry  # a re-run replaces its own earlier number
        else:
            runs.append(entry)
        res_path.write_text(json.dumps(results, indent=1))
        print(f"{arm:22s} {budget:4s} run {r}: macro {s['macro_exact_match']:.3f} {s['per_case_rate']}")

    for budget in a.budgets.split(","):
        for r in range(a.runs):
            # 1. the full system, live; its replies feed every replay arm
            full_log = None
            if "full system" in wanted or any(x in wanted for x in REPLAY_ARMS):
                answers, full_log = pipeline.run(items, budget, dict(pipeline.DEFAULT_CFG), call, a.workers)
                record("full system", budget, r, answers, full_log)
            # 2. symbolic components: replay the same replies
            for arm, off in REPLAY_ARMS.items():
                if arm not in wanted or (arm in ONLY_MULTI and budget == "1x"):
                    continue
                cfg = dict(pipeline.DEFAULT_CFG, **off)
                answers, _ = pipeline.run(items, budget, cfg, pipeline.replay_call_from(full_log), 1)
                record(arm, budget, r, answers, None)
            # 3. prompt components: fresh live runs
            for arm, off in LIVE_ARMS.items():
                if arm == "full system" or arm not in wanted:
                    continue
                if arm in ONLY_1X and budget != "1x":
                    continue
                cfg = dict(pipeline.DEFAULT_CFG, **off)
                answers, log = pipeline.run(items, budget, cfg, call, a.workers)
                record(arm, budget, r, answers, log)

    budgets = ["1x", "3x", "10x"]
    rows = ["| change from the submitted system | how measured | " + " | ".join(budgets) + " |",
            "|---|---|" + "---|" * len(budgets)]
    for arm in ORDER:
        how = "replay of full-system replies" if arm in REPLAY_ARMS else "live run"
        if arm == "full system":
            how = "live run"
        cells = []
        for b in budgets:
            runs = results.get(arm, {}).get(b)
            if not runs:
                cells.append("n/a")
                continue
            ms = [x["macro"] * 100 for x in runs]
            sd = f" ± {statistics.stdev(ms):.1f}" if len(ms) > 1 else ""
            cells.append(f"{statistics.mean(ms):.1f}{sd} (n={len(ms)})")
        rows.append(f"| {arm} | {how} | " + " | ".join(cells) + " |")
    (out / "ablation.md").write_text("\n".join(rows) + "\n")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
