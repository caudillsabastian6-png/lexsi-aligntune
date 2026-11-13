#!/usr/bin/env python3
"""Build dataset-b-TRAINING.jsonl from dataset-b.csv (protocol §3).

Prompt/completion pairs rendered with the EXACT baseline user template
(baseline-run/run_baseline_gguf.py build_prompt + RUN-CONFIG prompt_protocol):
the same INSTR string, same SOURCE/QUESTION/ANSWER layout, same
'(No source was provided.)' substitution for blank sources. Sources are the
verbatim source_text values from exam-v1-sources.json (the same texts the
baseline exam used). Completion = the row's corrected_response, verbatim.

Emission rule (protocol §4 / FINETUNE-PROTOCOL): the 14 trap/absent rows are
emitted once each; the single control row (LEX-C001) is emitted x4 as the
over-refusal counterweight. Total = 18 samples.

dataset-b-DRAFT.csv is never touched by this script; it reads the promoted
byte-identical copy dataset-b.csv only.
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

INSTR = ("Answer the question using ONLY the source below. Quote or closely "
         "paraphrase the source where you can. If the source does not contain "
         "the answer, say plainly that the source does not say.")

CONTROL_REPEATS = 4


def build_user_text(source_text, question):
    src = source_text if source_text.strip() else "(No source was provided.)"
    return f"{INSTR}\n\nSOURCE:\n{src}\n\nQUESTION: {question}\n\nANSWER:"


def main():
    rows = list(csv.DictReader(open(os.path.join(HERE, "dataset-b.csv"))))
    srcs = json.load(open(os.path.join(HERE, "exam-v1-sources.json")))
    assert len(rows) == 15, f"expected 15 Dataset B rows, got {len(rows)}"

    out = []
    for r in rows:
        iid = r["item_id"]
        assert r["holdout"] == "n", f"{iid}: holdout row leaked into Dataset B"
        assert iid in srcs, f"{iid}: no source in exam-v1-sources.json"
        user_text = build_user_text(srcs[iid]["source_text"], r["question"])
        rec = {
            "prompt": [{"role": "user", "content": user_text}],
            "completion": [{"role": "assistant",
                            "content": r["corrected_response"]}],
        }
        n = CONTROL_REPEATS if r["class"] == "control" else 1
        for _ in range(n):
            out.append(rec)
        print(f"{iid} ({r['class']}) x{n}")

    path = os.path.join(HERE, "dataset-b-TRAINING.jsonl")
    with open(path, "w") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"WROTE {path}: {len(out)} samples")
    return 0


if __name__ == "__main__":
    sys.exit(main())
