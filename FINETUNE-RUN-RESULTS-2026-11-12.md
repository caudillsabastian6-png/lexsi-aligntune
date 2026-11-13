# Lexsi AlignTune — Fine-Tune Run Results (relaunch of Nov 13, 2026)

Protocol: `FINETUNE-PROTOCOL-2026-11-12.md` (recipe and gate unchanged).
Predecessor record: `FINETUNE-RUN-2026-11-12.md` (run stopped at Step 0 —
no training job had ever run from this VM; the two Nov 12 jobs below were
submitted from a path whose failure modes were undiagnosed until today).

## Verdict (gate: trap ≤10% · control ≥58/60 · absent ≤6.7% · 0 gen failures)

## ✅ GATE: PASS — every leg, with maximum margin (checkpoint-60)

| Metric | Baseline Q4_K_M (Nov 8–11) | Tuned checkpoint-60 | Gate |
|---|---|---|---|
| Trap hallucination | 20.0% (12/60) | **0.0% (0/60)** | ≤10% |
| Control accuracy | 98.3% (59/60) | **100% (60/60)** | ≥58/60 |
| Absent hallucination | 6.7% (2/30) | **0.0% (0/30)** | ≤6.7% |
| Generation failures | 0 | **0** | 0 |

Full tuned detail: trap correct-abstain 60/60 (all six trap shapes
10/10), control over-refusals 0, absent correct-abstain 30/30
(no-source 10/10, off-topic-source 20/20). Not PARTIAL, not COLLAPSE:
a clean PASS under the protocol's pre-registered definitions. The
shippable artifact is the checkpoint-60 Q4_K_M GGUF (checkpoints 20
and 40 were not gate-examined; 60 was the designated final candidate
and passed outright).

Exam: exam-v1 (150 items, all `holdout == "n"`), identical prompts,
recording and grading code as the baseline Q4 run (greedy, seed
20261108, 160 max output tokens, n_ctx 4096). The sealed 45-item
holdout was never opened.

## Jobs — full history of this tune

| Job ID | Date (UTC) | Flavor | Outcome |
|---|---|---|---|
| 6af5c1be37daa033b62839f6 | Nov 12 | a10g-small | ERROR — v1 token design (see below) |
| 6af5c2c537daa033b6283c4c | Nov 12 | cpu-basic | ERROR — throwaway token probe, SyntaxError |
| 6af7504d29dd05ff036555a4 | Nov 13 | l4x1 | ERROR — job timeout during base-model load |
| 6af75b8323985fb9cd8054d3 | Nov 13 | l4x1 | ERROR — KeyError 'text' in SFTTrainer dataset prep |
| 6af7615229dd05ff03656cf6 | Nov 13 | l4x1 | COMPLETED — smoke (2 steps), full path proven |
| 6af7670923985fb9cd8060a9 | Nov 13 | a10g-large | ERROR — CUDA OOM at training step 5/60 |
| 6af7680a23985fb9cd806150 | Nov 13 | a100-large | **COMPLETED** — main tune, 13.3 min in-job, all artifacts |
| 6af76d2e23985fb9cd8064d0 | Nov 13 | cpu-performance | **COMPLETED** — checkpoint-60 gate exam job (below) |

## The three errored relaunch jobs — three DIFFERENT root causes

There is no single repeating cause. Each failure was a different layer
of the stack, and each was diagnosed from the job's own logs before the
next attempt:

1. **6af7504d (smoke 1) — volume-mount read speed.** v2's token-free
   design loads the base model from the `/base` volume mount. The
   transformers loader read safetensors through the mount at
   ~4 MB/s: shard 1 of 4 took 17 min 29 s (`Loading checkpoint shards:
   25% [17:29<52:29]`), and the 45-minute job timeout killed the job
   during load, before any training. Fix (v3): stage `/base` to the
   job's local disk with one sequential `cp -a` before any load
   (136 s on L4, 51 s on A100), then load locally (4 shards in 40 s).
2. **6af75b83 (smoke 2) — library API mismatch.** The bootstrap pinned
   `trl>=0.12,<0.14`; pip resolved TRL 0.13.0, whose SFTTrainer has
   **no prompt-completion support at all** (no `completion_only_loss`
   config field; dataset prep only handles plain-text or pre-tokenized
   datasets) and died with `KeyError: 'text'`. `train_lexsi.py` was
   written against the TRL ≥0.19 SFT API. Reproduced locally, then
   fixed by exact-pinning the verified stack (below). A fallback in
   the script also silently dropped completion-only loss under the old
   stack — v3.1 adds a hard guard: the job aborts unless the prepared
   dataset carries `completion_mask` (in the successful runs the log
   confirms "completion_mask present: completion-only loss in effect",
   and the example peek decodes the prompt/completion split correctly
   and ends with the EOT token; the same preparation was reproduced
   locally before the run: prepared columns
   [prompt, completion, input_ids, completion_mask], 47 of 285 tokens
   masked-in on the peeked example, exactly its assistant turn).
3. **6af76709 (main, first attempt) — GPU memory.** On a10g-large
   (22.3 GiB usable) training OOM'd at step 5/60 inside the
   cross-entropy over the 256k vocabulary: 21.71 GiB in use, a
   1.84 GiB allocation failed with 0.60 GiB free (2.58 GiB
   reserved-but-unallocated fragmentation). Nothing about the recipe
   changed: the job was resubmitted on `a100-large` with
   `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`. Training-data
   lengths were measured (223–322 tokens), so this was headroom, not
   sequence length.

The two Nov 12 jobs, for the record: 6af5c1be died after its in-job
`api.whoami()` raised `LocalTokenNotFoundError` — the Muse connector
surrogate token is proxy-local and cannot work inside an HF job (the
reason the v2 volume design exists). 6af5c2c5 was a throwaway probe
whose inline Python contained literal `\n` escapes (SyntaxError,
exit 1, $0.0005); it tested nothing.

## What changed vs the Nov 12 attempt (execution only — recipe untouched)

- `train_lexsi.py` v3.1: local-disk staging of the base (above);
  merges ordered 60 → 40 → 20 so the primary gate candidate's GGUF
  lands first; merged-bf16 writes to the bucket are opt-in
  (`LEXSI_WRITE_MERGED=1`, default off — they are the protocol's
  "while the budget allows" polish; GGUFs + adapters are the required
  artifacts); completion-mask guard (above). Recipe identical:
  LoRA r16/α32 all-linear, LR 1e-4 cosine, warmup 10%, bf16, batch 6,
  60 steps, checkpoints 20/40/60, seed 42, completion-only loss,
  template check with abort, 18 Dataset B rows (SHA unchanged).
- `lexsi_hf.py`: bootstrap pip line now exact-pins the locally
  verified stack — transformers 4.57.6, trl 0.19.1, peft 0.18.1,
  accelerate 1.11.0, datasets 3.6.0 (was: ranges resolving to
  trl 0.13.0). Smoke timeout 45 → 75 min. `PYTORCH_CUDA_ALLOC_CONF`
  added to the job env. Main was run on flavor `a100-large`
  (driver's `a10g-large` default was the OOM machine).
- Known driver wart (not hit in the runs): `lexsi_hf.py fetch-out`
  passes plain strings to `download_bucket_files`, which in
  huggingface_hub 2.4.0 requires (remote, local) tuples; outputs were
  fetched with a corrected one-off call instead.

## Spend

HF usage API, billing period Nov 1 – Dec 1, 2026 (account prepaid
$20, auto-recharge off):

- All jobs ever on this account before the relaunch: $0.80
  (a10g-small 48 min $0.800016 + cpu-basic 3 min $0.000501).
- This relaunch (Nov 13): **$2.03 total** — l4x1 smokes $0.8533
  (64 min) + a10g-large failed main $0.1000 (4 min) + a100-large main
  $0.6667 (16 min) + cpu-performance grading job $0.4117 (13 min).
  All-time jobs total after the relaunch: $2.8322 of the $20 prepaid
  credit (≈$17.17 remaining; auto-recharge off, no payment method
  linked, none ever requested by any screen).
- Hard ceiling for the relaunch was $8.00: **WITHIN — $2.03 spent
  (25% of ceiling).**

## Artifacts

- Adapters: bucket `CardCauldronTCG/lexsi-aligntune-out` →
  `adapters/checkpoint-{20,40,60}` (+ smoke `checkpoint-2`).
- GGUFs (Q4_K_M, 5,056,974,496 bytes each): bucket `gguf/checkpoint-{20,40,60}`
  (+ smoke `checkpoint-2`). Conversion used the script's fallback path
  (f16 convert + `llama-quantize`); direct Q4_K_M conversion from bf16
  was unsupported by the in-job llama.cpp build.
- Published model repo `CardCauldronTCG/aya-expanse-8b-lexsi-aligntune`:
  model card published Nov 13; GGUF + adapter publication follows the
  bucket→house transfer (see note in the grading paragraph — the
  bucket above is the canonical artifact home until then).
- Gate exam: run as HF job 6af76d2e23985fb9cd8064d0
  (cpu-performance, 13 min, $0.4117) because the bucket→VM download
  of the 5 GB GGUF stalled at ~0.2–0.9 MB/s (768 MB in ~35 min, then
  hung). The job mounted the bucket, copied the GGUF to local disk,
  and ran the identical lane: `tuned-audit/run_tuned_gguf.py` +
  `grade_tuned.py` (byte-identical grading logic to the baseline's
  `run_baseline_gguf.py` / `grade_q4.py`; only the model path and
  file names differ), exam/gold from the same files the baseline
  used. Total generation 671.6 s for 150 items. Outputs:
  `tuned-audit/answers-tuned.jsonl`, `tuned-audit/scoresheet-tuned.csv`,
  `tuned-audit/summary-tuned.json` (fetched from the bucket).

## Training run facts (job 6af7680a, a100-large)

- Bootstrap → python start ~2 min; base staged to local disk in 51 s;
  TEMPLATE_CHECK PASS; completion-mask guard PASS; example peek
  ends_with_eot=True.
- 60 optimizer steps in 46.8 s (20 epochs × 3 batches). Loss:
  step 1 (epoch 0.33) 4.127 → epoch 1 3.875 → epoch 2 2.918 →
  epoch 4 0.852 → epoch 8 0.122 → epoch 12 0.0007 → epochs 16–20
  ≈0.0002 (mean token accuracy 1.0 from epoch 12; mean train loss
  0.548). The 18-row Dataset B is memorized by design-era expectations;
  generalization is what the gate exam above measures — and it passed.
- Adapters for checkpoints 20/40/60 written 19:47:24 UTC; merges ran
  60 → 40 → 20 (GGUF-60 landed 19:50:53 UTC); job DONE at 19:57:59
  UTC, elapsed 13.3 min in-job.
