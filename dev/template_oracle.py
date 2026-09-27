# DEV ONLY. Never imported by pipeline.py and never used to answer items.
# A hand-written template matcher for the VISIBLE set phrasings. It stands in
# for a perfect extractor, to show the symbolic solver is correct: with it,
# the solver scores 100% on the visible set. It would not survive the held-out
# set, whose phrasings are different -- that is the point of using the model.
import re
PREFIXES = [r"It bears repeating: ", r"Noted twice in the handover: ", r"This came up more than once, so: ",
            r"Worth restating, since it came up twice in handover: "]
HEDGES = ["As far as I know, ", "My recollection is that ", "I'm fairly sure ", "Speaking from memory, ", "Going off the roster, "]
def strip(l):
    for p in PREFIXES:
        if l.startswith(p): l = l[len(p):]
    for p in HEDGES:
        if l.startswith(p): l = l[len(p):]
    return l[0].upper()+l[1:]
N = r"([A-Z][a-z]+)"; T = r"(\d\d:\d\d)"; S = r"([A-Za-z]+)"
def st(x): return {"station": x.lower()}
def R(pat): return re.compile("^"+pat.replace("{P}",N).replace("{T}",T).replace("{S}",S)+r"\.?$")
RULES = [
 (R(r"{P} sits between {P} and {P} on the rota"), lambda m:{"type":"between","mid":m[1],"a":m[2],"b":m[3]}),
 (R(r"Put {P} between {P} and {P}, though not necessarily next to either"), lambda m:{"type":"between","mid":m[1],"a":m[2],"b":m[3]}),
 (R(r"Whichever way round {P} and {P} are, {P} is between them"), lambda m:{"type":"between","mid":m[3],"a":m[1],"b":m[2]}),
 (R(r"{P} is on after one of {P} and {P} and before the other"), lambda m:{"type":"between","mid":m[1],"a":m[2],"b":m[3]}),
 (R(r"{P}'s block falls between {P}'s and {P}'s, in one order or the other"), lambda m:{"type":"between","mid":m[1],"a":m[2],"b":m[3]}),
 (R(r"{P} works at some point between {P} and {P}, not necessarily adjacent to either"), lambda m:{"type":"between","mid":m[1],"a":m[2],"b":m[3]}),
 (R(r"The {S} station is covered earlier in the day than {P}'s block"), lambda m:{"type":"before","a":st(m[1]),"b":m[2]}),
 (R(r"{S} is covered by someone other than {P}"), lambda m:{"type":"not_station","person":m[2],"station":m[1].lower()}),
 (R(r"Whoever is on {S} works earlier in the day than {P}"), lambda m:{"type":"before","a":st(m[1]),"b":m[2]}),
 (R(r"{P} is on later than whoever has {S}"), lambda m:{"type":"before","a":st(m[2]),"b":m[1]}),
 (R(r"The person on {S} precedes {P}"), lambda m:{"type":"before","a":st(m[1]),"b":m[2]}),
 (R(r"Whoever has {S} is done before {P} starts"), lambda m:{"type":"before","a":st(m[1]),"b":m[2]}),
 (R(r"{S} is covered before {P} comes on"), lambda m:{"type":"before","a":st(m[1]),"b":m[2]}),
 (R(r"{P} lobbied for {T} without success"), "NEG_WISH"),
 (R(r"{P} wanted {T} and did not get it"), "NEG_WISH"),
 (R(r"{P} put in for the {T} block and was turned down"), "NEG_WISH"),
 (R(r"{P} asked to move to the {T} block; the request was declined"), "NEG_WISH"),
 (R(r"{P} would have been a better fit for the {T} block"), "COUNTER"),
 (R(r"If {P} had taken the {T} block the handover would have been smoother"), "COUNTER"),
 (R(r"Had the rota gone the other way, {P} would be on {T}"), "COUNTER"),
 (R(r"Putting {P} on the {T} block would have solved the parking problem"), "COUNTER"),
 (R(r"There was some disagreement about whether {P} had {T}"), None),
 (R(r"The question of {P} on {T} was left open in the handover"), None),
 (R(r"Nobody could remember whether {P} was down for the {T} block"), None),
 (R(r"{P} and the {T} block came up, but nothing was minuted"), None),
 (R(r"In the spring {P} held {S} for a while"), None),
 (R(r"Back in the old arrangement, {P} took {S}"), None),
 (R(r"On the previous cycle {S} was {P}'s"), None),
 (R(r"Last month {P} was on {S}"), None),
 (R(r"{P} relieves {P} directly, with no block in between"), lambda m:{"type":"right_before","a":m[2],"b":m[1]}),
 (R(r"{P} has a standing commitment that rules out the {T} block entirely"), lambda m:{"type":"not_at","person":m[1],"block":m[2]}),
 (R(r"{P} has not been put on {S}"), lambda m:{"type":"not_station","person":m[1],"station":m[2].lower()}),
 (R(r"Whoever drew the {T} block, it was {P}"), lambda m:{"type":"at","person":m[2],"block":m[1]}),
 (R(r"{P} is not on {S}"), lambda m:{"type":"not_station","person":m[1],"station":m[2].lower()}),
 (R(r"You can rule {P} out for {S}"), lambda m:{"type":"not_station","person":m[1],"station":m[2].lower()}),
 (R(r"The {T} block is {P}'s"), lambda m:{"type":"at","person":m[2],"block":m[1]}),
 (R(r"There is no block between {P}'s and {P}'s, in that order"), lambda m:{"type":"right_before","a":m[1],"b":m[2]}),
 (R(r"{S} is {P}'s station"), lambda m:{"type":"station","person":m[2],"station":m[1].lower()}),
 (R(r"{S} is not {P}'s station"), lambda m:{"type":"not_station","person":m[2],"station":m[1].lower()}),
 (R(r"{P} is not assigned to {S}"), lambda m:{"type":"not_station","person":m[1],"station":m[2].lower()}),
 (R(r"{T} is the one block {P} is definitely not on"), lambda m:{"type":"not_at","person":m[2],"block":m[1]}),
 (R(r"{P} is unavailable at {T}"), lambda m:{"type":"not_at","person":m[1],"block":m[2]}),
 (R(r"By the time {P} starts, {P} has already been on"), lambda m:{"type":"before","a":m[2],"b":m[1]}),
 (R(r"{P} is the one who opens up at {T}"), lambda m:{"type":"at","person":m[1],"block":m[2]}),
 (R(r"{P} then {P}, back to back"), lambda m:{"type":"right_before","a":m[1],"b":m[2]}),
 (R(r"{P} comes later in the day than {P}"), lambda m:{"type":"before","a":m[2],"b":m[1]}),
 (R(r"{P} takes {T}, as things stand"), lambda m:{"type":"at","person":m[1],"block":m[2]}),
 (R(r"The {S} station is down to {P}"), lambda m:{"type":"station","person":m[2],"station":m[1].lower()}),
 (R(r"{P} is not on the {T} block"), lambda m:{"type":"not_at","person":m[1],"block":m[2]}),
 (R(r"{P} takes over from {P} later in the day"), "TAKEOVER"),
 (R(r"{P} is on the block directly after {P}"), lambda m:{"type":"right_before","a":m[2],"b":m[1]}),
 (R(r"You will not find {P} on the {T} block"), lambda m:{"type":"not_at","person":m[1],"block":m[2]}),
 (R(r"{P} is assigned to {S}"), lambda m:{"type":"station","person":m[1],"station":m[2].lower()}),
 (R(r"{P} is on the block immediately before {P}"), lambda m:{"type":"right_before","a":m[1],"b":m[2]}),
 (R(r"{P}'s block falls somewhere earlier than {P}'s"), lambda m:{"type":"before","a":m[1],"b":m[2]}),
 (R(r"{P} works earlier in the day than {P}"), lambda m:{"type":"before","a":m[1],"b":m[2]}),
 (R(r"{P} hands straight over to {P}"), lambda m:{"type":"right_before","a":m[1],"b":m[2]}),
 (R(r"{P} has {S} this week"), lambda m:{"type":"station","person":m[1],"station":m[2].lower()}),
 (R(r"{P} is on {S}"), lambda m:{"type":"station","person":m[1],"station":m[2].lower()}),
 (R(r"The {T} block is not {P}'s"), lambda m:{"type":"not_at","person":m[2],"block":m[1]}),
 (R(r"{S} is covered by {P}"), lambda m:{"type":"station","person":m[2],"station":m[1].lower()}),
 (R(r"{T} is when {P} is scheduled"), lambda m:{"type":"at","person":m[2],"block":m[1]}),
 (R(r"{P} is on the {T} block"), lambda m:{"type":"at","person":m[1],"block":m[2]}),
 (R(r"{P} is done before {P} starts"), lambda m:{"type":"before","a":m[1],"b":m[2]}),
]
def extract(line, mode):
    s = strip(line)
    for rx, f in RULES:
        m = rx.match(s)
        if m:
            if f is None: return None
            if isinstance(f, str):
                opt = mode.get(f)
                return opt(m) if opt else None
            return f(m)
    return None
