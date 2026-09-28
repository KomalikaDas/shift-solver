# Shift notes with a weak model

## The short version

Granite 4.2 8B can't solve these rota puzzles on its own. The brief says it scored 0%. So I don't ask it to. I only ask it to read each line of the notes and rewrite it in a small, fixed format, like `Rohan BEFORE Ayesha` or `Meera NOT_ON packing`, or `NONE` if the line doesn't matter.

Python does the rest. It tries every possible rota (only a few hundred per item) and counts how many fit all the constraints:

- exactly 1 fits → **unique**
- 2 to 4 fit → **ambiguous**, and I return all of them
- none fit → **inconsistent**. To find which lines clash, I remove lines one at a time. If the rest still clash without a line, that line wasn't needed. What's left is a smallest set of lines that can't all be true together.

Results on the 60 visible items (macro exact match):

- Granite alone: 0% (from the brief)
- My system at 1×: between 58.3% and 65.0% over three runs
- At 3×: [TBD]%
- At 10×: [TBD]%

## How to run it

Python 3.12. Install the pinned packages with `pip install -r requirements.txt`, then:

```
./run <items.json> --budget <1x|3x|10x> --out <answers.json>
```

The key, URL and model name are read from `.env`. Environment variables with the same names override it. Every call sends the `X-Item-Id` header and uses temperature 1.0, top_p 0.95, with thinking turned off. There are no automatic retries, because a retry would be an extra call and could break the budget. At 1× each item gets exactly one call. At 3× and 10× it gets exactly 3 or 10.

To rerun the ablation: `python ablate.py`

## Results

| budget | macro % | runs | where it ran |
|---|---|---|---|
| 1× | 60.0 and 65.0 | 2 | provided endpoint |
| 1× | [TBD] | 3 | local Granite on Kaggle |
| 3× | [TBD] | 1 | local Granite on Kaggle |
| 10× | [TBD] | 1 | local Granite on Kaggle |

What the system declared vs the true kind, for the 65.0% run:

| true ↓ / declared → | unique | ambiguous | inconsistent |
|---|---|---|---|
| unique | 13 | 5 | 2 |
| ambiguous | 1 | 18 | 1 |
| inconsistent | 1 | 2 | 17 |

Most mistakes are unique items called ambiguous. That usually means Granite missed one constraint, so more than one rota fitted. This is the kind of mistake extra calls at 3× and 10× should fix.

**Why some runs are on Kaggle:** the API key I was given ran out of credit after about 500 calls, partway through the ablation. For the rest I ran the same Granite 4.2 8B model myself, using Ollama on Kaggle's free GPUs, which the brief allows for development. I used the 8-bit version (`granite4.2:8b-q8_0`), with the same settings and thinking off. Its 1× score (58.3%) was close to the endpoint runs (60.0% and 65.0%), so I think the numbers can be compared, but I keep them in separate rows because they're not exactly the same setup.

## How I got to know the model

First I checked my own code. I wrote a rough pattern-matcher for the visible sentences (in `dev/`, only used for testing, never for answering) and gave its perfect translations to the solver. It scored 100%. That told me every mistake after that would come from Granite's reading of the lines, not from the logic.

Then I wrote `dev/diagnose.py`. It compares Granite's translation of every single line with the correct one and groups the mistakes by sentence type. Almost every change I made came from looking at its output. What I learned:

1. **Granite thinks out loud even with thinking turned off.** It often repeats the sentence, argues with itself, and puts the right answer at the end. For example: `"Meera has not been put on packing." — means Meera is not on packing station. So "Meera NOT_ON packing"`. My first parser grabbed the word "on" from the quoted sentence and got it wrong.
2. **It copies words from the example in the prompt.** My first example used the real station names, and Granite started writing "intake" for lines about calibration. Once I switched the example to made-up names and stations, this stopped.
3. **It mixes up order and direction.** With `BETWEEN M X Y` it often put the wrong person in the middle. "Nadia relieves Meera" came out backwards 9 times.
4. **It adds things that aren't there.** For "Packing is covered by someone other than Ayesha" it gave the right answer plus four extra made-up time constraints for Ayesha.
5. **It writes "either/or" answers with a semicolon.** For "Nadia is on after one of Samuel and Ingrid and before the other" it gave two alternatives separated by `;`. That's a correct reading, just in a form I hadn't expected.
6. **It rarely treats filler lines as facts**, only 0.7% of the time. The main exception is lines like "Tomas wanted 09:00 and did not get it". Granite reads these as "Tomas is not on 09:00". That's fair logically, but the answer key treats them as filler.

Overall, Granite translated 86.1% of lines correctly in my first version and 92.2% in the final one.

## What each part is for

| part | what it does | why it's there |
|---|---|---|
| Line-by-line translation | Granite never solves, only translates | Granite alone scores 0% |
| Normal word order, plus AFTER and JUST_AFTER | Granite can write `Samuel BETWEEN Meera Priya` and "A AFTER B" the way the sentence says it | point 3 |
| Example with made-up names | shows the format without giving away real words | point 2 |
| Rules for what counts as NONE | past events, wishes, "what if"s and open questions are ignored | by far the most important part (see ablation) |
| One rule on direction | "relieves" or "takes over from" means after, "hands over to" means before | "relieves" errors fell from 9 to 2 |
| Last answer wins, keywords in capitals | read Granite's conclusion, not the sentence it quoted | point 1 |
| Type fix | `Ayesha NOT_AT calibration` is read as NOT_ON, because calibration is a station, not a time | Granite mixing up AT and ON |
| Grounding check | throws away any constraint that uses a name, station or time that isn't in that line | point 4 |
| Either/or reading | if one line's parts contradict each other, treat them as alternatives | point 5. In these notes a single line never contradicts itself, since real conflicts always need at least 3 lines |
| Voting (3×, 10×) | for each line, take the answer most samples agree on | random variation between calls |
| Plausibility check (3×, 10×) | prefer a result that fits what the task promises: 1 to 4 rotas, or a conflict of at least 3 lines | readings that are clearly broken |

I measured the parser fixes without spending any new calls. I saved Granite's replies and ran them through the new code again, so the model's answers were exactly the same and only my code changed. On one saved run, the score went 36.7% → 45.0% (capitals and type fix) → 50.0% (last answer wins) → 53.3% (either/or reading). The direction rule changed the prompt, so it needed a fresh run, which scored 63.3%.

## Ablation

For each part, I turned it off and measured the score again.

- Parts that change the **prompt** need a new live run.
- Parts that only change **what happens after Granite replies** are tested by rerunning the full system's saved replies with that part switched off. This way the comparison uses exactly the same model answers, so any difference comes from that part alone.

[TBD: full table from `results_kaggle/ablation.md`]

The 1× results on the provided endpoint (one run, before the credit ran out):

| turned off | 1× macro % |
|---|---|
| nothing (full system) | 60.0 |
| rules for NONE | 13.3 |
| worked example | 38.3 |
| grounding check | 51.7 |
| last answer wins | 56.7 |
| either/or reading | 60.0 |
| prefilter | 65.0 |

I didn't run the prompt parts at 10×, because I didn't have enough GPU time. The table says "n/a" there rather than guessing.

## Things I built and then removed

- **My first prompt.** It used `BETWEEN M X Y` style and an example with the real station names. Points 2 and 3 above are why I replaced it. The old version is in `dev/history/prompt_v1.py`.
- **The prefilter.** It skipped lines with no name, time or station in them, to save tokens. Turning it off didn't hurt, and even scored 5 points higher in the one endpoint run. [TBD: say whether I removed it, based on the Kaggle numbers.]

## Where it still fails

- **Sentences like "Whoever is on intake works earlier than Priya".** This is Granite's weakest pattern. It understands a station is involved, but it can't put a station where a person should go, and writes things like `intake AT earlier than Priya`. My code rejects that, the constraint is lost, and the item usually ends up as ambiguous.
- **"Wanted X and didn't get it" lines** are still sometimes read as facts.
- **At 1× there's no second chance.** One wrong line means a wrong answer. The plausibility check can notice a broken result, but with one call it can't fix it.
- **The header is read with fixed patterns (regex).** That works for this template, but a differently written header would break the system before Granite even sees the notes.
- **I tuned everything on these 60 items.** The hidden test set uses different wording. I wrote my rules in general English instead of copying the visible sentences, but I still expect a lower score there.

## Model-based or symbolic?

Reading the constraints is **model-based**. Granite translates every line. Everything else is symbolic: reading the header, checking the translations, voting, solving and finding conflicts.

**If real people wrote the notes:** New ways of saying the same thing ("between", "not on", "after") are exactly what Granite is there for, and my checks after it don't depend on wording. So that part should hold up. Messier writing would cause problems, though:
- Pronouns like "she's on packing" would be thrown away by the grounding check, because the name isn't in the line.
- Relative times like "first thing" or "the late shift" would also be thrown away, because the grounding check wants the actual time written in the line.
- One long sentence covering several people breaks my "one line, one fact" assumption.

The upside is that most of these failures lose a constraint rather than invent one. So the system would lean towards answering "ambiguous" rather than being confidently wrong.

## If I had a month

- Use the extra calls more cleverly: instead of repeating the whole item, re-ask Granite only about the lines where its samples disagreed.
- Give Granite an easier way to handle "whoever is on intake" sentences, maybe in two steps: first "who is on intake?", then the ordering.
- Handle pronouns and relative times, and loosen the grounding check to allow them.
- Build my own test set by rewriting the visible sentences in new words, to measure how much the score drops on unfamiliar wording instead of guessing.
- Do more runs per number. Most numbers here come from one run, and runs vary by about 5 points.

## What's in the repo

- `run` and `pipeline.py`: the system
- `prompt.py`: what Granite is asked
- `solver.py`: reads the header, tries every rota, finds conflicts
- `llm.py`: the only file that talks to the model
- `ablate.py`: the ablation
- `dev/`: my testing tools, never used to answer items
- `results/`: runs on the provided endpoint. `results_kaggle/`: runs on local Granite

I used Claude as a coding assistant while building this, which the brief allows. No frontier model is used to answer items.
