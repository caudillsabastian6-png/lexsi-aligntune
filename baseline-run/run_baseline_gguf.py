#!/usr/bin/env python3
"""Lexsi baseline audit — GGUF lane (llama-cpp-python), UNTOUCHED Aya Expanse 8B.

Why this lane: the VM has ~6 GB usable RAM; the bf16 safetensors (16 GB)
cannot be loaded by transformers here at all. The GGUF lane runs the same
untouched base model (bartowski conversion of CohereLabs/aya-expanse-8b)
in two precisions on identical prompts:
  Q8_0   -> answers-q8.jsonl   (primary baseline record)
  Q4_K_M -> answers-q4.jsonl   (cross-check; same file the G1 carries,
                                sha256 9592bad9...)
Prompt protocol, decoding (greedy, max 160 new tokens, seed 20261108) and
exam split (150 main items, holdout=n only; sealed holdout never opened)
match run_baseline.py exactly. Local CPU only, $0.
Resumable: completed item_ids in each answers file are skipped.
"""
import csv, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
BLD = os.path.dirname(HERE)
GGUF_DIR = os.path.join(HERE, "aya-gguf")
MAX_NEW = 160
INSTR = ("Answer the question using ONLY the source below. Quote or closely "
         "paraphrase the source where you can. If the source does not contain "
         "the answer, say plainly that the source does not say.")

def build_prompt(source_text, question):
    src = source_text if source_text.strip() else "(No source was provided.)"
    return f"{INSTR}\n\nSOURCE:\n{src}\n\nQUESTION: {question}\n\nANSWER:"

def run_one(model_path, ans_path, rows, srcs):
    from llama_cpp import Llama
    done = set()
    if os.path.exists(ans_path):
        for line in open(ans_path):
            if line.strip():
                done.add(json.loads(line)["item_id"])
    todo = [r for r in rows if r["item_id"] not in done]
    print(f"{os.path.basename(model_path)}: total={len(rows)} done={len(done)} todo={len(todo)}", flush=True)
    if not todo:
        print("NOTHING TO DO"); return
    t0 = time.time()
    llm = Llama(model_path=model_path, n_ctx=4096, n_threads=4, seed=20261108, verbose=False)
    print(f"model loaded in {time.time()-t0:.0f}s", flush=True)
    out = open(ans_path, "a")
    for i, r in enumerate(todo):
        prompt = build_prompt(srcs[r["item_id"]]["source_text"], r["question"])
        t1 = time.time()
        res = llm(prompt=(f"<|START_OF_TURN_TOKEN|><|USER_TOKEN|>{prompt}"
                          f"<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"),
                  max_tokens=MAX_NEW, temperature=0.0, seed=20261108,
                  stop=["<|END_OF_TURN_TOKEN|>", "<|START_OF_TURN_TOKEN|>"])
        dt = time.time() - t1
        ans = res["choices"][0]["text"].strip()
        n_out = res["usage"]["completion_tokens"]
        n_in = res["usage"]["prompt_tokens"]
        rec = {"item_id": r["item_id"], "class": r["class"],
               "kind": srcs[r["item_id"]]["kind"], "answer": ans,
               "input_tokens": int(n_in), "output_tokens": int(n_out),
               "seconds": round(dt, 1)}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
        print(f"[{i+1}/{len(todo)}] {r['item_id']} ({r['class']}) {dt:.0f}s out_tok={n_out} :: {ans[:80]!r}", flush=True)
    out.close()
    print(f"RUN COMPLETE {os.path.basename(model_path)} total_wall={time.time()-t0:.0f}s", flush=True)
    del llm

def main():
    rows = list(csv.DictReader(open(os.path.join(BLD, "exam-v1.csv"))))
    assert all(r["holdout"] == "n" for r in rows), "non-main row leaked into exam-v1"
    srcs = json.load(open(os.path.join(BLD, "exam-v1-sources.json")))
    which = sys.argv[1] if len(sys.argv) > 1 else "q8"
    if which in ("q8", "both"):
        run_one(os.path.join(GGUF_DIR, "aya-expanse-8b-Q8_0.gguf"),
                os.path.join(HERE, "answers-q8.jsonl"), rows, srcs)
    if which in ("q4", "both"):
        run_one(os.path.join(GGUF_DIR, "aya-expanse-8b-Q4_K_M.gguf"),
                os.path.join(HERE, "answers-q4.jsonl"), rows, srcs)

if __name__ == "__main__":
    main()
