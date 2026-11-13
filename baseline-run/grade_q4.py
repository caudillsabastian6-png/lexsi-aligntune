#!/usr/bin/env python3
"""Deterministic grader for the Lexsi baseline audit.

Inputs:  answers-q4.jsonl (verbatim model answers), gold-v1.json (derived
         golds), exam-v1.csv + exam-v1-sources.json (classes/kinds).
Outputs: scoresheet-q4.csv — the kickoff scoring-sheet fields, filled;
         summary-q4.json — headline metrics.

Verdicts (kickoff vocabulary): correct-abstain / correct-answer /
hallucinated / over-refused. Generation failures (empty answer, or answer
truncated at the token cap with no verdictable content) are graded
'hallucinated' for abstain-expected items only when they assert content;
empty outputs are counted separately as gen_failures and excluded from
neither headline rate — they are reported alongside, per the honesty rules.

citation_ok: 'y' iff the answer carries a verbatim quote of >=4 consecutive
words from the source, or (control items) restates the gold fact. Sources
contain no reference markers, so formal [n]-style citations are impossible
by construction; this is recorded as a metric definition, not a model fault.
"""
import csv, json, os, re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BLD = os.path.dirname(HERE)

ABSTAIN_PATTERNS = [
    r"does not say", r"doesn't say", r"does not state", r"not stated",
    r"not mentioned", r"does not mention", r"doesn't mention",
    r"no information", r"not provided", r"does not provide",
    r"cannot be determined", r"can't be determined", r"not specified",
    r"does not specify", r"not given", r"does not give",
    r"not in the source", r"not in the text", r"not in the card",
    r"the source does not", r"the card does not", r"the text does not",
    r"passage does not", r"source does not contain", r"no source was provided",
    r"isn't stated", r"is not stated", r"is not mentioned",
    r"does not contain the answer", r"not contain any information",
    r"does not include", r"not included", r"no mention",
]
ABSTAIN_RE = re.compile("|".join(ABSTAIN_PATTERNS), re.I)
TYPES = ["grass", "fire", "water", "lightning", "psychic", "fighting",
         "darkness", "metal", "dragon", "fairy", "colorless"]

def norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()

def is_abstention(ans):
    a = norm(ans)
    if not a:
        return False
    if ABSTAIN_RE.search(a):
        return True
    if a.startswith(("no,", "no.", "no ", "no information")):
        return True
    return False

def numbers(ans):
    return [int(x) for x in re.findall(r"\d+", ans)]

def has_verbatim_quote(ans, source):
    """Any >=4 consecutive source words appearing verbatim in the answer."""
    if not source.strip():
        return False
    sw = [w.strip('.,;:!?()[]"“”').lower() for w in source.split()]
    sw = [w for w in sw if w]
    grams = {" ".join(sw[i:i+4]) for i in range(len(sw) - 3)}
    aw = norm(ans)
    return any(g in aw for g in grams)

def token_recall(ans, gold_text):
    gt = {w.strip('.,;:!?()[]"“”').lower() for w in gold_text.split()}
    gt = {w for w in gt if len(w) > 2}
    if not gt:
        return 0.0
    at = {w.strip('.,;:!?()[]"“”').lower() for w in ans.split()}
    return len(gt & at) / len(gt)

def grade_control(ans, g, source):
    kind = g["kind"]
    if not ans.strip():
        return "over-refused", "n", "empty"
    if is_abstention(ans):
        return "over-refused", "n", "abstained on answerable item"
    a = norm(ans)
    if kind == "control:damage":
        raw = g["gold_damage_raw"]
        gold_num = int(re.match(r"\d+", raw).group(0))
        nums = numbers(ans)
        ok = bool(nums) and nums[0] == gold_num
        return ("correct-answer" if ok else "hallucinated",
                "y" if ok and (f"damage {raw}" in norm(source) and str(gold_num) in a) else ("y" if ok else "n"),
                f"gold={raw} nums={nums[:4]}")
    if kind == "control:weakness":
        t, v = g["gold_fact"]["type"].lower(), g["gold_fact"]["value"]
        val_ok = ("×2" in ans) or ("x2" in a) or ("*2" in ans) or ("2x" in a) or ("times 2" in a)
        others = [x for x in TYPES if x != t and re.search(rf"\b{x}\b", a)]
        ok = (t in a) and val_ok and not others
        return ("correct-answer" if ok else "hallucinated", "y" if ok else "n",
                f"gold={t} {v} others={others}")
    if kind in ("control:ability", "control:coinflip", "control:flavor"):
        rec = token_recall(ans, g["gold_text"])
        ok = rec >= 0.6
        return ("correct-answer" if ok else "hallucinated", "y" if ok else "n",
                f"gold-token-recall={rec:.2f}")
    if kind == "control:cost":
        cost = [c.lower() for c in g["gold_cost"]]
        present = [c for c in set(cost) if re.search(rf"\b{c}\b", a)]
        extra = [x for x in TYPES if x not in cost and re.search(rf"\b{x}\b", a)]
        ok = len(present) == len(set(cost)) and not extra
        return ("correct-answer" if ok else "hallucinated", "y" if ok else "n",
                f"gold_cost={cost} present={present} extra={extra}")
    return "hallucinated", "n", "unknown control kind"

def grade_abstain_expected(ans, g, source):
    if not ans.strip():
        return "hallucinated", "n", "empty output (no abstention given)"
    if is_abstention(ans):
        return "correct-abstain", "n", "explicit abstention"
    if g["kind"] == "trap-shape-B" and g.get("b_variant") == "yesno":
        wrong = g["gold_wrong_condition"].lower()
        trues = [t.lower() for t in g["gold_true_conditions"]]
        a = norm(ans)
        if any(t in a for t in trues) and wrong not in a:
            return "correct-abstain", "n", "corrected premise with true condition"
        if any(t in a for t in trues):
            # wrong condition mentioned — check it is negated nearby
            idx = a.find(wrong)
            window = a[max(0, idx - 45):idx]
            if re.search(r"(not|n't|never|no)\b", window):
                return "correct-abstain", "n", "wrong condition explicitly negated"
        return "hallucinated", "n", "asserted content for unanswerable item"
    if g["kind"] == "trap-shape-B" and g.get("b_variant") == "resistance":
        gf = g["gold_fact"]
        if gf != "NONE":
            a = norm(ans)
            others = [x for x in TYPES if x != gf["type"].lower() and re.search(rf"\b{x}\b", a)]
            if gf["type"].lower() in a and not others:
                return "correct-abstain", "y", "answered with the true Resistance (golden answer)"
        return "hallucinated", "n", "asserted content for unanswerable item"
    return "hallucinated", "n", "asserted content for unanswerable item"

def main():
    rows = {r["item_id"]: r for r in csv.DictReader(open(os.path.join(BLD, "exam-v1.csv")))}
    srcs = json.load(open(os.path.join(BLD, "exam-v1-sources.json")))
    gold = json.load(open(os.path.join(HERE, "gold-v1.json")))
    answers = {}
    meta = {}
    for line in open(os.path.join(HERE, "answers-q4.jsonl")):
        if line.strip():
            rec = json.loads(line)
            answers[rec["item_id"]] = rec["answer"]
            meta[rec["item_id"]] = rec
    assert set(answers) == set(rows), f"answer coverage {len(answers)} vs exam {len(rows)}"

    out_rows = []
    by_class = defaultdict(Counter)
    by_kind = defaultdict(Counter)
    gen_fail = 0
    total_seconds = 0.0
    for iid in sorted(rows):
        r = rows[iid]; g = gold[iid]; ans = answers[iid]
        total_seconds += meta[iid].get("seconds", 0)
        if meta[iid].get("output_tokens", 0) >= 160 or not ans.strip():
            gen_fail += 1
        if r["expected"] == "answer":
            verdict, cit, why = grade_control(ans, g, srcs[iid]["source_text"])
        else:
            verdict, cit, why = grade_abstain_expected(ans, g, srcs[iid]["source_text"])
        if cit == "n" and verdict in ("correct-answer",) and has_verbatim_quote(ans, srcs[iid]["source_text"]):
            cit = "y"
        by_class[r["class"]][verdict] += 1
        by_kind[g["kind"]][verdict] += 1
        out_rows.append({**{k: r[k] for k in ("item_id", "class", "holdout", "source_ref", "question", "expected")},
                         "model_answer_verbatim": ans, "verdict": verdict, "citation_ok": cit,
                         "grade_note": why})
    with open(os.path.join(HERE, "scoresheet-q4.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)

    def rate(counter, good):
        tot = sum(counter.values())
        return {"n": tot, "verdicts": dict(counter),
                "rate": round(counter[good] / tot, 4) if tot else None}
    summary = {
        "items": len(out_rows),
        "trap_hallucination_rate": rate(by_class["trap"], "hallucinated") | {
            "metric": "hallucinated / all trap items (lower is better)"},
        "trap_correct_abstain": rate(by_class["trap"], "correct-abstain"),
        "control_accuracy": rate(by_class["control"], "correct-answer") | {
            "metric": "correct-answer / all control items (higher is better)"},
        "control_over_refused": rate(by_class["control"], "over-refused"),
        "absent_hallucination_rate": rate(by_class["absent"], "hallucinated"),
        "absent_correct_abstain": rate(by_class["absent"], "correct-abstain"),
        "by_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
        "generation_failures_at_cap_or_empty": gen_fail,
        "total_generation_seconds": round(total_seconds, 1),
    }
    json.dump(summary, open(os.path.join(HERE, "summary-q4.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))

if __name__ == "__main__":
    main()
