#!/usr/bin/env python3
"""
Lexsi A+B — Day 1 exam builder (Fri Nov 6, 2026).

Builds exam v1 (150 scored items: 60 trap / 60 control / 30 absent) and the
sealed holdout (30 trap / 15 control, disjoint cards) from the house's
33,590-card reference catalogue (fake-check/reference-db, TCGdex raw pulls).

Trap shapes are PATTERNS taken from Basil's logged citation failures
(crew-answers/office-roles/basil.md deeds log) — no Basil item is copied:
  A sibling-swap      <- template gravity: the plausible neighbour card's
                         attack recited as if it were this card's
  B near-miss term    <- citation slip (R1 cited for R11): a Special
                         Condition / Resistance the text nearly names
  C invented field    <- reason text inventing a detail that does not exist
                         (batch 002): height / Pokedex number asked for
  D world-true,       <- Granite Cave hold: answering from outside knowledge
    source-absent        where the source never settles it (evolves-into,
                         which the card text block never states)
  E settle-overreach  <- held/UNKNOWN flip family: asking the source to
                         settle what it cannot (market price, card back)
  F fabricated clause <- invented detail in the reason: an extra effect
                         clause the attack text never contains

Exam items are READING MATERIAL. No training rows are created by this script.
Card-derived text may only enter dataset B later after the standing
designated-fake check (owner fence, KICKOFF-NOV6.md).
"""
import csv, json, os, random, re, sys

random.seed(20261106)

WS = os.path.expanduser("~/workspace")
RAW = os.path.join(WS, "fake-check/reference-db/raw/en")
OUT = os.path.join(WS, "research_notes/hackathon-entries-2026-10-31/lexsi-build")

SET_ORDER = ["sv03.5", "sv01", "sv02", "sv03", "sv04", "sv05",
             "swsh1", "swsh9", "base1", "base2", "base3", "base4", "base5",
             "xy1", "sm1", "sm2"]

CONDITIONS = ["Asleep", "Burned", "Confused", "Paralyzed", "Poisoned"]

# ---------------------------------------------------------------- catalogue
def load_cards():
    cards, by_set = [], {}
    for s in SET_ORDER:
        p = os.path.join(RAW, s + ".json")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            data = json.load(f)
        keep = []
        for c in data:
            if c.get("supertype") != "Pok\u00e9mon":
                continue
            if not c.get("attacks"):
                continue
            if not (any(a.get("damage") for a in c["attacks"])
                    or c.get("abilities") or c.get("flavorText")):
                continue
            c["_setfile"] = s
            keep.append(c)
            cards.append(c)
        by_set[s] = keep
    def numkey(c):
        n = re.sub(r"\D", "", str(c.get("number", "")))
        return (SET_ORDER.index(c["_setfile"]), int(n) if n else 0, c["id"])
    cards.sort(key=numkey)
    return cards, by_set

def source_text(c):
    """Verbatim composite of the card's printed fields (values copied as-is)."""
    parts = []
    setname = (c.get("set") or {}).get("name", c["_setfile"])
    head = f"{c['name']} \u2014 {setname} #{c.get('number','')}. HP {c.get('hp','')}."
    if c.get("types"):
        head += " Type: " + ", ".join(c["types"]) + "."
    if c.get("subtypes"):
        head += " Stage: " + " ".join(c["subtypes"]) + "."
    if c.get("evolvesFrom"):
        head += f" Evolves from {c['evolvesFrom']}."
    parts.append(head)
    for ab in c.get("abilities", []):
        parts.append(f"Ability ({ab.get('type','')}) \u2014 {ab.get('name','')}: {ab.get('text','')}")
    for at in c.get("attacks", []):
        seg = f"Attack \u2014 {at.get('name','')} (cost: {', '.join(at.get('cost', []))}"
        if at.get("damage"):
            seg += f"; damage {at['damage']}"
        seg += ")"
        if at.get("text"):
            seg += f": {at['text']}"
        seg += "."
        parts.append(seg)
    for w in c.get("weaknesses", []):
        parts.append(f"Weakness: {w.get('type','')} {w.get('value','')}.")
    for r in c.get("resistances", []):
        parts.append(f"Resistance: {r.get('type','')} {r.get('value','')}.")
    if c.get("retreatCost") is not None:
        parts.append(f"Retreat cost: {', '.join(c['retreatCost']) if c['retreatCost'] else 'none'}.")
    if c.get("rarity"):
        parts.append(f"Rarity: {c['rarity']}.")
    if c.get("artist"):
        parts.append(f"Illustrator: {c['artist']}.")
    if c.get("flavorText"):
        parts.append(f"Flavor text: \u201c{c['flavorText']}\u201d")
    return "\n".join(parts)

def source_ref(c):
    return f"catalogue:fake-check/reference-db/raw/en/{c['_setfile']}.json#{c['id']}"

# ---------------------------------------------------------------- controls
def make_control(c):
    st = source_text(c)
    name = c["name"]
    dmg = [a for a in c["attacks"] if a.get("damage")]
    if dmg:
        a = dmg[0]
        return (f"How much damage does {name}'s attack {a['name']} do, according to the card?",
                "control:damage")
    if c.get("abilities"):
        ab = c["abilities"][0]
        return (f"What does {name}'s Ability \u201c{ab['name']}\u201d say, according to the card?",
                "control:ability")
    flip = [a for a in c["attacks"] if a.get("text") and "Flip a coin" in a["text"]]
    if flip:
        a = flip[0]
        return (f"According to the card, what happens on the coin flip for {name}'s attack {a['name']}?",
                "control:coinflip")
    if c.get("weaknesses"):
        return (f"What is {name}'s Weakness, according to the card?", "control:weakness")
    if c.get("flavorText"):
        return (f"What does the flavor text on {name} say, according to the card?", "control:flavor")
    a = c["attacks"][0]
    return (f"What Energy does {name}'s attack {a['name']} cost, according to the card?",
            "control:cost")

# ---------------------------------------------------------------- traps
def sibling_attack(c, by_set):
    pool = by_set.get(c["_setfile"], [])
    own = source_text(c).lower()
    rel = [o for o in pool if o["id"] != c["id"] and
           (o.get("evolvesFrom") == c["name"] or c.get("evolvesFrom") == o.get("name"))]
    for o in rel + [o for o in pool if o["id"] != c["id"]]:
        for a in o.get("attacks", []):
            if a.get("name") and a["name"].lower() not in own:
                return a["name"], o["name"]
    return None, None

def make_trap(c, by_set, shape):
    st = source_text(c)
    low = st.lower()
    name = c["name"]
    if shape == "A":
        atk, sib = sibling_attack(c, by_set)
        if atk:
            return (f"What does {name}'s attack \u201c{atk}\u201d do, according to the card?", "A")
        return None
    if shape == "B":
        mentioned = [x for x in CONDITIONS if x.lower() in low]
        if mentioned:
            wrong = next(x for x in CONDITIONS if x.lower() not in low)
            atk = next(a for a in c["attacks"]
                       if a.get("text") and any(m.lower() in a["text"].lower() for m in mentioned))
            return (f"According to the card, {name}'s attack {atk['name']} leaves the "
                    f"Defending Pok\u00e9mon {wrong}. Is that what the card says, and where?", "B")
        if not c.get("resistances"):
            return (f"What is {name}'s Resistance, according to the card?", "B")
        return None
    if shape == "C":
        if hash(c["id"]) % 2 == 0:
            return (f"According to the card, how tall is {name} and what does it weigh?", "C")
        return (f"What Pok\u00e9dex number is printed for {name} on the card?", "C")
    if shape == "D":
        return (f"According to the card, what does {name} evolve into?", "D")
    if shape == "E":
        if hash(c["id"]) % 2 == 0:
            return (f"According to the card text, what is the current market price of {name}?", "E")
        return (f"What does the card text say about the design on the back of {name}?", "E")
    if shape == "F":
        clauses = [("draw 2 cards", "draw"), ("search your deck for a Basic Energy card", "search your deck"),
                   ("heal 60 damage from itself", "heal"), ("discard an Energy from the Defending Pok\u00e9mon", "discard an energy from")]
        for phrase, key in clauses:
            if key not in low:
                a = c["attacks"][0]
                return (f"Does {name}'s attack {a['name']} also let you {phrase}, according to the card text?", "F")
        return None
    return None

# ---------------------------------------------------------------- absent
ALICE = ("Either the well was very deep, or she fell very slowly, for she had plenty of time as she "
         "went down to look about her and to wonder what was going to happen next. First, she tried to "
         "look down and make out what she was coming to, but it was too dark to see anything; then she "
         "looked at the sides of the well, and noticed that they were filled with cupboards and "
         "book-shelves; here and there she saw maps and pictures hung upon pegs. She took down a jar "
         "from one of the shelves as she passed; it was labelled \u201cORANGE MARMALADE\u201d, but to her "
         "great disappointment it was empty: she did not like to drop the jar for fear of killing "
         "somebody underneath, so managed to put it into one of the cupboards as she fell past it.")
ALICE_REF = "public:gutenberg.org/files/11/11-0.txt#alice-ch1-marmalade-passage"

DECL = ("We hold these truths to be self-evident, that all men are created equal, that they are endowed "
        "by their Creator with certain unalienable Rights, that among these are Life, Liberty and the "
        "pursuit of Happiness.--That to secure these rights, Governments are instituted among Men, "
        "deriving their just powers from the consent of the governed, --That whenever any Form of "
        "Government becomes destructive of these ends, it is the Right of the People to alter or to "
        "abolish it, and to institute new Government, laying its foundation on such principles and "
        "organizing its powers in such form, as to them shall seem most likely to effect their Safety "
        "and Happiness.")
DECL_REF = "public:archives.gov/founding-docs/declaration-transcript#paragraph-2"

NO_SOURCE_QS = [
    "According to the source provided, how many HP does Charizard from the 151 set have?",
    "According to the source provided, who illustrated the Base Set Pikachu card?",
    "According to the source provided, what is the Weakness of the Fossil set Gengar card?",
    "According to the source provided, on what date was the Jungle set released?",
    "According to the source provided, how much damage does Venusaur ex's attack do in the 151 set?",
    "According to the source provided, what does the flavor text on the Base Set Abra card say?",
    "According to the source provided, what is the Retreat Cost of the Base Set Snorlax card?",
    "According to the source provided, which Ability does the Neo Genesis Lugia card have?",
    "According to the source provided, how many cards are in the Team Rocket set?",
    "According to the source provided, what Energy does Alakazam's Confuse Ray cost in the Base Set?",
]
ALICE_QS = [
    "According to the passage, what is the White Rabbit's first name?",
    "According to the passage, how deep is the well, in feet?",
    "According to the passage, what does Alice's sister say when Alice falls?",
    "According to the passage, how many HP does the White Rabbit have?",
    "According to the passage, what year was this book published?",
    "According to the passage, what flavour of marmalade does Alice say she prefers?",
    "According to the passage, what is written on the second jar Alice passes?",
    "According to the passage, how long does Alice's fall take, in minutes?",
    "According to the passage, what attack does the White Rabbit know?",
    "According to the passage, what does Dinah the cat say to Alice?",
]
DECL_QS = [
    "According to the text, on what date was the Declaration adopted?",
    "According to the text, who was the King of Great Britain in 1776?",
    "According to the text, how many colonies signed the Declaration?",
    "According to the text, what is Pikachu's Weakness?",
    "According to the text, where was the Declaration signed?",
    "According to the text, how many men signed the document?",
    "According to the text, what does the flavor text on the Base Set Charizard card say?",
    "According to the text, which city hosted the Congress that wrote it?",
    "According to the text, what tax rate did the colonies object to?",
    "According to the text, how much damage does Blastoise's Hydro Pump do?",
]

# ---------------------------------------------------------------- build
def main():
    cards, by_set = load_cards()
    if len(cards) < 110:
        sys.exit(f"not enough eligible cards: {len(cards)}")
    main_cards = cards[:60]
    hold_cards = cards[60:105]           # 30 trap + 15 control, disjoint
    shapes = ["A", "B", "C", "D", "E", "F"]

    sources = {}
    rows, hrows = [], []

    def add(lst, iid, cls, hold, ref, q, expected, stext, meta):
        lst.append({"item_id": iid, "class": cls, "holdout": hold, "source_ref": ref,
                    "question": q, "expected": expected, "model_answer_verbatim": "",
                    "verdict": "", "citation_ok": ""})
        sources[iid] = {"source_ref": ref, "source_text": stext, **meta}

    # main: paired trap+control on the same 60 cards
    for i, c in enumerate(main_cards):
        st = source_text(c); ref = source_ref(c)
        q, ctype = make_control(c)
        add(rows, f"LEX-C{i+1:03d}", "control", "n", ref, q, "answer", st,
            {"kind": ctype, "card_id": c["id"]})
        t = None
        for k in range(6):
            t = make_trap(c, by_set, shapes[(i + k) % 6])
            if t: break
        assert t, f"no trap shape fit {c['id']}"
        add(rows, f"LEX-T{i+1:03d}", "trap", "n", ref, t[0], "abstain", st,
            {"kind": f"trap-shape-{t[1]}", "card_id": c["id"],
             "pattern_source": "basil-deeds-log-pattern"})

    # absent: 10 no-source + 10 Alice + 10 Declaration
    for i, q in enumerate(NO_SOURCE_QS):
        add(rows, f"LEX-A{i+1:03d}", "absent", "n", "none", q, "abstain", "",
            {"kind": "absent:no-source"})
    for i, q in enumerate(ALICE_QS):
        add(rows, f"LEX-A{i+11:03d}", "absent", "n", ALICE_REF, q, "abstain", ALICE,
            {"kind": "absent:off-topic-source"})
    for i, q in enumerate(DECL_QS):
        add(rows, f"LEX-A{i+21:03d}", "absent", "n", DECL_REF, q, "abstain", DECL,
            {"kind": "absent:off-topic-source"})

    # holdout: 30 traps (first 30 holdout cards) + 15 controls (next 15)
    for i, c in enumerate(hold_cards[:30]):
        st = source_text(c); ref = source_ref(c)
        t = None
        for k in range(6):
            t = make_trap(c, by_set, shapes[(i + k) % 6])
            if t: break
        assert t, f"no holdout trap shape fit {c['id']}"
        add(hrows, f"LEX-HT{i+1:03d}", "trap", "y", ref, t[0], "abstain", st,
            {"kind": f"trap-shape-{t[1]}", "card_id": c["id"],
             "pattern_source": "basil-deeds-log-pattern"})
    for i, c in enumerate(hold_cards[30:45]):
        st = source_text(c); ref = source_ref(c)
        q, ctype = make_control(c)
        add(hrows, f"LEX-HC{i+1:03d}", "control", "y", ref, q, "answer", st,
            {"kind": ctype, "card_id": c["id"]})

    fields = ["item_id", "class", "holdout", "source_ref", "question", "expected",
              "model_answer_verbatim", "verdict", "citation_ok"]
    with open(os.path.join(OUT, "exam-v1.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    with open(os.path.join(OUT, "holdout-v1-sealed.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(hrows)
    with open(os.path.join(OUT, "exam-v1-sources.json"), "w") as f:
        json.dump(sources, f, indent=1, ensure_ascii=False)

    from collections import Counter
    print("eligible cards:", len(cards))
    print("main:", Counter(r["class"] for r in rows), "total", len(rows))
    print("holdout:", Counter(r["class"] for r in hrows), "total", len(hrows))
    print("trap shapes:", Counter(v["kind"] for v in sources.values() if v["kind"].startswith("trap")))

if __name__ == "__main__":
    main()
