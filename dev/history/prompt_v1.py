"""The extraction prompt. The model only translates; it never solves."""

FORMS = """Constraint forms (X, Y, M are a person's name or a station name; a station
name stands for whoever is on that station):
  AT X <block>          X works that block
  NOT_AT X <block>      X does not work that block
  ON <person> <station>      the person is on that station
  NOT_ON <person> <station>  the person is not on that station
  BEFORE X Y            X's block is earlier in the day than Y's (any gap)
  NEXT X Y              Y's block comes straight after X's, no block in between
  BETWEEN M X Y         M's block is somewhere between X's and Y's, either order"""

NOISE_RULES = """How to read the lines:
- Hedges do not weaken anything. "I think", "as far as I know", "I'm fairly sure",
  "from memory" and similar: translate the statement as a plain fact.
- A line repeated with "It bears repeating:" or similar is translated normally.
- Write NONE when the line puts no condition on today's blocks or stations:
  * it is about something else (car-sharing, keys, training, surveys, weather)
  * it is about the past or another rota ("last month", "previous cycle",
    "in the old arrangement", "back in the spring")
  * it is a wish or request, granted or not ("wanted 11:00", "asked for",
    "was turned down", "lobbied for")
  * it is hypothetical ("would have", "if she had", "had things gone differently")
  * it only says something is unknown or undecided ("nobody remembers whether",
    "was left open", "there was disagreement about", "came up but nothing decided")
- Watch direction. "A comes after B" is BEFORE B A. "A takes over from B later"
  is BEFORE B A. "A hands straight over to B" is NEXT A B."""

EXAMPLES = """Example rota: Alice, Bob, Carla, Dev, Emma. Blocks 07:00, 09:00, 11:00,
13:00, 15:00. Stations: intake, packing, calibration.
Example lines:
1. Honestly, I reckon Bob has the 09:00 slot.
2. Carla is not the one on packing.
3. Dev starts only once Emma has finished.
4. Whoever runs intake is on earlier than Alice.
5. Alice car-pools with Dev on Fridays.
6. Carla had hoped for 13:00 but it went elsewhere.
7. Emma goes on right after Bob, nothing in between.
8. Somewhere between Alice's shift and Dev's, in whichever order, you'll find Carla.
9. Last quarter Bob ran calibration.
10. Calibration is Emma's job today.
11. If Dev had been on 07:00 we'd have saved an hour.
12. It's still unclear whether Alice is down for 15:00.
13. 11:00 is definitely not Bob's.
Answer:
1: AT Bob 09:00
2: NOT_ON Carla packing
3: BEFORE Emma Dev
4: BEFORE intake Alice
5: NONE
6: NONE
7: NEXT Bob Emma
8: BETWEEN Carla Alice Dev
9: NONE
10: ON Emma calibration
11: NONE
12: NONE
13: NOT_AT Bob 11:00"""


def build(header, lines, examples=True, noise_rules=True):
    """header: parsed rota. lines: list of (number, text) to translate."""
    parts = [
        "You translate shift-note lines into a fixed constraint language. "
        "Do not solve the rota. Translate each line on its own.",
        "",
        "Rota: " + ", ".join(header["staff"]) + ".",
        "Blocks: " + ", ".join(header["blocks"]) + ".",
        "Stations: " + ", ".join(header["stations"]) + ".",
        "",
        FORMS,
    ]
    if noise_rules:
        parts += ["", NOISE_RULES]
    if examples:
        parts += ["", EXAMPLES]
    parts += [
        "",
        "Output one line per numbered line, in the form '<number>: <constraint>' or "
        "'<number>: NONE'. If one line states two conditions, join them with ' ; '. "
        "Use names, blocks and stations exactly as written above. Output nothing else.",
        "",
        "Lines:",
    ]
    parts += [f"{n}. {t}" for n, t in lines]
    return [{"role": "user", "content": "\n".join(parts)}]
