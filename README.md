# Shift notes with a weak model

## The short version

Granite 4.2 8B can't solve these rota puzzles on its own. The brief says it scored 0%, and I got the same 0% when I asked it directly. So I don't ask it to solve anything. I only ask it to read each line of the notes and rewrite it in a small, fixed format, like `Rohan BEFORE Ayesha` or `Meera NOT_ON packing`, or `NONE` if the line doesn't matter.

Python does the rest. It tries every possible rota (a few hundred per item) and counts how many fit all the constraints:

- exactly 1 fits → **unique**
- 2 to 4 fit → **ambiguous**, and I return all of them
- none fit → **inconsistent**. To find which lines clash, I remove lines one at a time. If the rest still clash without a line, that line wasn't needed. What's left is a smallest set of lines that can't all be true together.

Results on the 60 visible items (macro exact match, final system):

| budget | score | runs |
|---|---|---|
| Granite alone, no system | 0.0% | 1 |
| 1× | 58.3% ± 6.0 | 3 |
| 3× | 75.0% | 1 |
| 10× | 76.7% | 1 |

Most of the gain from extra calls comes by 3×. Going from 3× to 10× adds very little. More on why below.

## How to run it

Python 3.12. Install the pinned packages with `pip install -r requirements.txt`, then:

```
./run <items.json> --budget <1x|3x|10x> --out <answers.json>
```

The key, URL and model name are read from `.env` (`OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `MODEL`). Environment variables with the same names override it. Every call sends the `X-Item-Id` header and uses temperature 1.0, top_p 0.95, with thinking turned off. There are no automatic retries, because a retry would be an extra call and could break the budget. At 1× each item gets exactly one call. At 3× and 10× it gets exactly 3 or 10.

To rerun the ablation: `python ablate.py --out-dir results_rerun`. Use a new folder name: `ablate.py` adds to any results already in the folder it's given. With the defaults (every change, every budget, one run each) it makes about 3,400 model calls. To run fewer, use `--budgets 1x` or pick changes with `--arms`.

## Where the numbers come from

The API key I was given ran out of credit after about 500 calls, partway through my first ablation. For everything after that, I ran the same Granite 4.2 8B model myself, using Ollama on Kaggle's free GPUs (2× T4), which the brief allows for development. I used the 8-bit version (`granite4.2:8b-q8_0`), with the same sampling settings and thinking turned off. The submitted code still uses the provided endpoint by default. The local setup is only switched on with `LLM_BACKEND=ollama`.

To check the two setups behave alike, I compared 1× scores. On the endpoint I got 60.0% and 65.0%. Locally, with the same code, the three runs averaged 57.8%. That's close enough that I think the numbers can be compared, but they're not identical, so I keep them apart.

- `results_kaggle/`: the final system on local Granite. **All the headline numbers and the ablation table come from here.**
- `results_kaggle_prefilter_on/`: an earlier local run, with the prefilter still switched on.
- `results/`: runs on the provided endpoint, all with the prefilter still on.

## Case handling

What the system declared vs the true kind. The 1× table adds up all three runs, so each row totals 60.

| 1×, 3 runs | declared unique | declared ambiguous | declared inconsistent |
|---|---|---|---|
| true unique | 41 | 12 | 7 |
| true ambiguous | 1 | 50 | 9 |
| true inconsistent | 6 | 4 | 50 |

| 10×, 1 run | declared unique | declared ambiguous | declared inconsistent |
|---|---|---|---|
| true unique | 15 | 3 | 2 |
| true ambiguous | 0 | 18 | 2 |
| true inconsistent | 2 | 1 | 17 |

Each kind is mostly recognised as itself, and nothing collapses into a single answer. At 1× the right kind is declared for about 78% of items, but only 58% are fully correct. The difference is items with the right kind but slightly wrong content, like a real conflict cited with one wrong line. The most common wrong kind is a unique item called ambiguous. That happens when Granite misses one constraint, so more than one rota fits.

## How I got to know the model

First I checked my own code. I wrote a rough pattern-matcher for the visible sentences (in `dev/`, only used for testing, never for answering) and gave its perfect translations to the solver. It scored 100%. That told me every mistake after that would come from Granite's reading of the lines, not from the logic.

Then I wrote `dev/diagnose.py`. It compares Granite's translation of every single line with the correct one and groups the mistakes by sentence type. Almost every change I made came from looking at its output. What I learned:

1. **Granite thinks out loud even with thinking turned off.** It often repeats the sentence, argues with itself, and puts the right answer at the end. For example: `"Meera has not been put on packing." — means Meera is not on packing station. So "Meera NOT_ON packing"`. My first parser grabbed the word "on" from the quoted sentence and got it wrong.
2. **It copies words from the example in the prompt.** My first example used the real station names, and Granite started writing "intake" for lines about calibration. Once I switched the example to made-up names and stations, this stopped.
3. **It mixes up order and direction.** With `BETWEEN M X Y` it often put the wrong person in the middle. "Nadia relieves Meera" came out backwards 9 times.
4. **It adds things that aren't there.** For "Packing is covered by someone other than Ayesha" it gave the right answer plus four extra made-up time constraints for Ayesha.
5. **It writes "either/or" answers with a semicolon.** For "Nadia is on after one of Samuel and Ingrid and before the other" it gave two alternatives separated by `;`. That's a correct reading, just in a form I hadn't expected.
6. **It rarely treats filler lines as facts**, only 0.7% of the time. The main exception is lines like "Tomas wanted 09:00 and did not get it". Granite reads these as "Tomas is not on 09:00". That's fair logically, but the answer key treats them as filler.

Overall, Granite translated 86.1% of lines correctly in my first version and 92.2% after the changes below.

## What each part is for

| part | what it does | why it's there |
|---|---|---|
| Line-by-line translation | Granite never solves, only translates | Granite alone scores 0% |
| Normal word order, plus AFTER and JUST_AFTER | Granite can write `Samuel BETWEEN Meera Priya` and "A AFTER B" the way the sentence says it | point 3 |
| Example with made-up names | shows the format without giving away real words | point 2 |
| Rules for what counts as NONE | past events, wishes, "what if"s and open questions are ignored | the most important part (see ablation) |
| One rule on direction | "relieves" or "takes over from" means after, "hands over to" means before | "relieves" errors fell from 9 to 2 |
| Last answer wins, keywords in capitals | read Granite's conclusion, not the sentence it quoted | point 1 |
| Type fix | `Ayesha NOT_AT calibration` is read as NOT_ON, because calibration is a station, not a time | Granite mixing up AT and ON |
| Grounding check | throws away any constraint that uses a name, station or time that isn't in that line | point 4 |
| Either/or reading | if one line's parts contradict each other, treat them as alternatives | point 5. In these notes a single line never contradicts itself, since real conflicts always need at least 3 lines |
| Voting (3×, 10×) | for each line, take the answer most samples agree on | random variation between calls |
| Plausibility check (3×, 10×) | prefer a result that fits what the task promises: 1 to 4 rotas, or a conflict of at least 3 lines | readings that are clearly broken |

I measured the early parser fixes without spending any new calls. I saved Granite's replies from one endpoint run and ran them through each new version of my code, so the model's answers stayed exactly the same and only the parsing changed. The score went 36.7% → 45.0% (capitals and type fix) → 50.0% (last answer wins) → 53.3% (either/or reading). The direction rule changed the prompt, so it needed a fresh run, which scored 63.3%.

## Ablation

For each part, I changed only that part and measured again. There are two ways of measuring:

- Parts that change the **prompt** need a new live run.
- Parts that only change **what happens after Granite replies** are tested by rerunning the full system's saved replies with that part switched off. Both sides of the comparison use exactly the same model answers, so any difference comes from that part alone.

Local Granite, final system (`results_kaggle/ablation.md`). The number in brackets is how many runs.

| change from the submitted system | how measured | 1× | 3× | 10× |
|---|---|---|---|---|
| none (full system) | live run | 58.3 ± 6.0 (3) | 75.0 (1) | 76.7 (1) |
| no grounding check | replay | 54.4 ± 4.2 (3) | 70.0 (1) | 70.0 (1) |
| no "last answer wins" | replay | 55.6 ± 6.9 (3) | 68.3 (1) | 76.7 (1) |
| no either/or reading | replay | 57.2 ± 5.8 (3) | 76.7 (1) | 76.7 (1) |
| no voting | replay | n/a | 70.0 (1) | 73.3 (1) |
| no plausibility check | replay | n/a | 71.7 (1) | 71.7 (1) |
| prefilter switched back on | live run | 58.3 (1) | 63.3 (1) | not run |
| no worked example | live run | 41.7 (1) | 63.3 (1) | not run |
| no rules for NONE | live run | 35.0 (1) | 45.0 (1) | not run |
| Granite answers directly | live run | 0.0 (1) | not run | not run |

What I take from it:

- **The prompt matters most.** Without the rules for NONE, 1× falls from 58.3 to 35.0. Without the worked example, it falls to 41.7. The endpoint run showed the same order (13.3 and 38.3 without them).
- **The grounding check helps at every budget**, by 4 to 7 points.
- **Voting and the plausibility check only help when there are several samples**, by about 3 to 5 points each at 3× and 10×. In my earlier run (prefilter on), voting didn't help at 3×, so I wouldn't trust the exact size.
- **The either/or reading makes no real difference.** Removing it changed the score by −1.1, +1.7 and 0 points at 1×, 3× and 10×. I kept it because it's cheap and correct, but the data doesn't show it helping.
- I didn't run the prompt changes at 10×, because I didn't have enough GPU time. The table says "not run" instead of guessing.
- Most numbers come from one run, and 1× runs of the same system varied from 53.3 to 65.0. Differences of a few points in single runs could be noise.

## Why 3× to 10× barely helps

Going from 1× to 3× adds about 17 points. Going from 3× to 10× adds under 2. My explanation, which I haven't tested directly: voting fixes Granite's random mistakes, but many of its mistakes aren't random. It fails on the same sentence types every time, like "whoever is on intake works earlier than Priya" and "wanted 09:00 and did not get it" (see below). If Granite gets a line wrong in most samples, ten samples just vote for the wrong answer more confidently. More samples can't fix a mistake the model makes every time. That needs a different prompt or a different way of asking about those lines.

## Things I built and then removed

- **My first prompt.** It used `BETWEEN M X Y` style and an example with the real station names. Points 2 and 3 above are why I replaced it. The old version is in `dev/history/prompt_v1.py`.
- **The prefilter.** It skipped lines with no name, time or station in them, to save tokens and hopefully reduce noise. Every time I compared, it did worse or no better:

| comparison | with prefilter | without |
|---|---|---|
| 1×, endpoint | 60.0 | 65.0 |
| 1×, local, earlier run | 57.8 (avg of 3) | 65.0 |
| 1×, local, final run | 58.3 | 58.3 (avg of 3) |
| 3×, local, earlier run | 60.0 | 73.3 |
| 3×, local, final run | 63.3 | 75.0 |

At 1× the difference is within run-to-run noise. At 3× it's large both times. So I switched it off. It's still in the code as an option (`--prefilter`), so the ablation can test it. I don't know for sure why it hurts. My guess is that seeing every line, including the filler, helps Granite understand the notes and practise writing NONE, but I haven't tested that.

## Where it still fails

- **Sentences like "Whoever is on intake works earlier than Priya".** This is Granite's weakest pattern. It understands a station is involved, but it can't put a station where a person should go, and writes things like `intake AT earlier than Priya`. My code rejects that, the constraint is lost, and the item usually ends up as ambiguous.
- **"Wanted X and didn't get it" lines** are still sometimes read as facts.
- **At 1× there's no second chance.** One wrong line means a wrong answer. The plausibility check can notice a broken result, but with one call it can't fix it.
- **The header is read with fixed patterns (regex).** That works for this template, but a differently written header would break the system before Granite even sees the notes.
- **I tuned everything on these 60 items.** The hidden test set uses different wording. I wrote my rules in general English instead of copying the visible sentences, but I still expect a lower score there.
- **About the 10× score:** 76.7% is higher than the 67.5% the brief quotes for Claude Sonnet 5. But that's one run, on items I tuned against, and using ten calls against its one. I don't think it means much beyond "the system uses extra calls well up to a point".

## Model-based or symbolic?

Reading the constraints is **model-based**. Granite translates every line. Everything else is symbolic: reading the header, checking the translations, voting, solving and finding conflicts.

**If real people wrote the notes:** New ways of saying the same thing ("between", "not on", "after") are exactly what Granite is there for, and my checks after it don't depend on wording. So that part should hold up. Messier writing would cause problems, though:

- Pronouns like "she's on packing" would be thrown away by the grounding check, because the name isn't in the line.
- Relative times like "first thing" or "the late shift" would also be thrown away, because the grounding check wants the actual time written in the line.
- One long sentence covering several people breaks my "one line, one fact" assumption.

The upside is that most of these failures lose a constraint rather than invent one. So the system would lean towards answering "ambiguous" rather than being confidently wrong.

## If I had a month

- Use the extra calls more cleverly: instead of repeating the whole item, re-ask Granite only about the lines where its samples disagreed. That targets the plateau above.
- Give Granite an easier way to handle "whoever is on intake" sentences, maybe in two steps: first "who is on intake?", then the ordering.
- Handle pronouns and relative times, and loosen the grounding check to allow them.
- Build my own test set by rewriting the visible sentences in new words, to measure how much the score drops on unfamiliar wording instead of guessing.
- Do more runs per number. Most numbers here come from one run, and runs vary by about 5 points.
- Find out why the prefilter hurts, instead of guessing.

## What's in the repo

- `run` and `pipeline.py`: the system
- `prompt.py`: what Granite is asked
- `solver.py`: reads the header, tries every rota, finds conflicts
- `llm.py`: the only file that talks to the model (the provided endpoint by default, local Ollama if `LLM_BACKEND=ollama`)
- `ablate.py`: the ablation
- `dev/`: my testing tools, never used to answer items: `oracle_check.py`, `diagnose.py`, `replay.py` (replaying a log made with the prefilter on needs `--prefilter`), `template_oracle.py`, `history/`
- `results/`, `results_kaggle_prefilter_on/`, `results_kaggle/`: see "Where the numbers come from"

I used Claude as a coding assistant while building this, which the brief allows. No frontier model is used to answer items.
