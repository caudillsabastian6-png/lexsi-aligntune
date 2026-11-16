# AlignTune: Teaching a Small Model to Say "I Don't Know"

**Lexsi AI Safety & Alignment Hackathon — Stage 1**
Solo participant: Sabastian Caudill

## Problem

Small open models confidently invent answers when the honest answer is
"unknown / not in the evidence." To measure this, we built a purpose-built
150-item exam:

- **60 trap items** — questions baiting a hallucinated citation or fact
- **60 control items** — answerable questions the model must still get right
- **30 absent items** — the needed fact is not present, so the correct
  behavior is to say so

## Baseline

Base model: [CohereLabs/aya-expanse-8b](https://huggingface.co/CohereLabs/aya-expanse-8b),
evaluated as a Q4_K_M GGUF with greedy decoding (seed 20261108, recorded run
config in `baseline-run/`):

| Metric | Baseline |
|---|---|
| Trap hallucination | 20.0% (12/60) |
| Control accuracy | 98.3% (59/60) |
| Absent hallucination | 6.7% (2/30) |
| Generation failures | 0 |

## Dataset B

A fenced curriculum of corrected responses teaching "say unknown when it is
unknown" without damaging control accuracy. Before any training use it passed
15/15 designated-fake checks and 15/15 spot checks.

Re-audited in full on Nov 15, 2026: 14 of the 15 corrected responses were
confirmed verbatim and one (LEX-T048) was tightened for directness. The
tuned model was trained on the pre-tightening text — see the addendum in
`FINETUNE-RUN-RESULTS-2026-11-12.md` and `SPOTCHECK-2026-11-15.md`.

Dataset: https://huggingface.co/datasets/CardCauldronTCG/lexsi-dataset-b

## Fine-tune — GATE PASS ✅

LoRA (rank 16, alpha 32, learning rate 1e-4 cosine, 60 steps, checkpoints
at 20/40/60, completion-only loss) trained on Dataset B, then re-graded on
the same exam. The gate was pre-registered before training started:

- **PASS** = trap hallucination ≤ 10%, control ≥ 58/60, absent ≤ 6.7%,
  0 generation failures.

Checkpoint-60 result (exam-v1, 150 items):

| Metric | Baseline | Tuned (ckpt-60) | Gate |
|---|---|---|---|
| Trap hallucination | 20.0% (12/60) | **0.0% (0/60)** | ≤10% |
| Control accuracy | 98.3% (59/60) | **100% (60/60)** | ≥58/60 |
| Absent hallucination | 6.7% (2/30) | **0.0% (0/30)** | ≤6.7% |
| Generation failures | 0 | **0** | 0 |

**Verdict: PASS on every leg — 150/150 items correct.** One honest note:
the 18 Dataset B training rows are memorized during training by design
(training loss → ~0). The exam above is a separate 150-item set the model
was not trained on; generalization is what it measures. Full record:
`FINETUNE-RUN-RESULTS-2026-11-12.md`.

Model: https://huggingface.co/CardCauldronTCG/aya-expanse-8b-lexsi-aligntune

## Integrity

A 45-item holdout was sealed by SHA-256 before any tuning and has never been
opened during development:

```
holdout-v1-sealed.csv  SHA-256  ade3f7af8ce5f220edd3f16d29ab82aed459d1fd8718f9ae54d72bfca7b642c5
```

(The sealed file itself is deliberately not in this repo.)
All reported numbers come from the development exam (`exam-v1.csv`) and are
reproducible from the recorded run configuration.

## Contents

- `train_lexsi.py` — LoRA training script (runs on Hugging Face Jobs)
- `lexsi_hf.py` — HF Jobs driver (prep / submit / status / logs / usage);
  it uses a dynamic credential surrogate and contains no token
- `build_training_input.py` — builds the training JSONL from Dataset B
- `build_exam_v1.py` — builds the development exam and the sealed holdout
- `baseline-run/run_baseline_gguf.py`, `baseline-run/grade_q4.py` —
  baseline runner and grader
- `exam-v1.csv` — the 150-item development exam
- `FINETUNE-PROTOCOL-2026-11-12.md` — the pre-registered fine-tune protocol
- `FINETUNE-RUN-RESULTS-2026-11-12.md` — training runs and the gate verdict
- `BASELINE-AUDIT.md` — baseline audit record

## Links

- Models collection: https://huggingface.co/collections/CardCauldronTCG/lexsi-aligntune-models-6af750e5307f37a24a8e95c5
- Datasets collection: https://huggingface.co/collections/CardCauldronTCG/lexsi-aligntune-datasets-6af750e6a81fe397ad13d5ab

## License

MIT
