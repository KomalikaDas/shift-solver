"""The extraction prompt (v2). The model only translates; it never solves.

v1 -> v2, each change answering a failure measured with dev/diagnose.py on the
first 1x run (see README):
  - constraints are written in English word order ("Samuel BETWEEN Meera Priya")
    instead of prefix form ("BETWEEN Samuel Meera Priya"): v1 mixed up which
    name was in the middle
  - AFTER / JUST_AFTER exist alongside BEFORE / JUST_BEFORE, so the model can
    keep the sentence's own direction instead of flipping it
  - the worked example uses invented names, stations and times: v1's example
    shared the real station names and the model copied them into its answers
"""

FORMS = """Write each constraint in the same word order as a plain sentence:
  X AT <block>            X works that block
  X NOT_AT <block>        X does not work that block
  <person> ON <station>       the person is on that station
  <person> NOT_ON <station>   the person is not on that station
  X BEFORE Y              X's block is earlier than Y's (any gap)
  X AFTER Y               X's block is later than Y's (any gap)
  X JUST_BEFORE Y         X's block is immediately before Y's, no block in between
  X JUST_AFTER Y          X's block is immediately after Y's, no block in between
  M BETWEEN X Y           M's block lies somewhere between X's and Y's, in either order
X, Y and M are a person's name, or a station name meaning whoever is on that station."""

NOISE_RULES = """How to read the lines:
- Hedges do not weaken anything. "I think", "as far as I know", "I'm fairly sure",
  "from memory" and similar: translate the statement as a plain fact.
- A line that repeats another ("It bears repeating:" and the like) is translated normally.
- Any line saying one person is between two others is BETWEEN, however it is worded:
  "sits between", "falls between", "after one of them and before the other",
  "whichever way round A and B are, M is between them". M is the one in the middle.
- A line usually gives exactly one constraint. Never list extra constraints the
  line does not state, and only use names, stations and blocks that appear in it
  (a station named in the line may stand for whoever is on it).
- Write NONE when the line puts no condition on today's blocks or stations:
  * it is about something else (car-sharing, keys, training, surveys, weather)
  * it is about the past or another rota ("last month", "previous cycle",
    "in the old arrangement", "back in the spring")
  * it is a wish or request, granted or not ("wanted 11:00", "asked for",
    "was turned down", "lobbied for")
  * it is hypothetical ("would have", "if she had", "had things gone differently")
  * it only says something is unknown or undecided ("nobody remembers whether",
    "was left open", "there was disagreement about", "came up but nothing decided")"""

EXAMPLES = """Worked example (a different rota, only to show the format):
Rota: Alice, Bob, Carla, Dev, Emma. Blocks: 06:00, 08:00, 10:00, 12:00, 14:00.
Stations: loading, sorting, labelling.
Lines:
1. Honestly, I reckon Bob has the 08:00 slot.
2. Carla is not the one on sorting.
3. Dev starts only once Emma has finished.
4. Whoever runs loading is on earlier than Alice.
5. Alice car-pools with Dev on Fridays.
6. Carla had hoped for 12:00 but it went elsewhere.
7. Emma goes on right after Bob, nothing in between.
8. Somewhere between Alice's shift and Dev's, in whichever order, you'll find Carla.
9. Last quarter Bob ran labelling.
10. Labelling is Emma's job today.
11. If Dev had been on 06:00 we'd have saved an hour.
12. It's still unclear whether Alice is down for 14:00.
13. 10:00 is definitely not Bob's.
14. Dev is on later than whoever has sorting.
Answer:
1: Bob AT 08:00
2: Carla NOT_ON sorting
3: Dev AFTER Emma
4: loading BEFORE Alice
5: NONE
6: NONE
7: Emma JUST_AFTER Bob
8: Carla BETWEEN Alice Dev
9: NONE
10: Emma ON labelling
11: NONE
12: NONE
13: Bob NOT_AT 10:00
14: Dev AFTER sorting"""


def build(header, lines, examples=True, noise_rules=True):
    """header: parsed rota. lines: list of (number, text) to translate."""
    parts = [
        "You translate shift-note lines into a fixed constraint language. "
        "Do not solve the rota. Translate each line on its own.",
        "",
        FORMS,
    ]
    if noise_rules:
        parts += ["", NOISE_RULES]
    if examples:
        parts += ["", EXAMPLES]
    parts += [
        "",
        "Now the real rota.",
        "Rota: " + ", ".join(header["staff"]) + ".",
        "Blocks: " + ", ".join(header["blocks"]) + ".",
        "Stations: " + ", ".join(header["stations"]) + ".",
        "",
        "Output one line per numbered line, as '<number>: <constraint>' or "
        "'<number>: NONE'. If one line really states two conditions, join them with ' ; '. "
        "Use names, blocks and stations exactly as written. Output nothing else.",
        "",
        "Lines:",
    ]
    parts += [f"{n}. {t}" for n, t in lines]
    return [{"role": "user", "content": "\n".join(parts)}]
