# Fine-tune Protocol — Lexsi AlignTune (written Nov 12, 2026)

**Status: GROUNDWORK ONLY. No training run has happened, no credit has
been spent, no job has been submitted.** This file is the executable
protocol whose absence stopped the Nov 12 run
(`FINETUNE-RUN-2026-11-12.md`, blocker 1). The owner approved the
HF-credit tune route on Nov 12, 2026, after the morning stop report
and the passed fence checks. Every number below is a decision
recorded here, in writing, before any run — per the stop report's
unblock condition 1.

Deadline: **Stage 1 submission due Sunday Nov 15, 2026, 11:59 PM AoE.**
The sealed holdout (`holdout-v1-sealed.csv`, SHA-256
`ade3f7af8ce5f220edd3f16d29ab82aed459d1fd8718f9ae54d72bfca7b642c5`)
is never opened by anything in this protocol until Step 7, and is
never trained on.

---

## 1. HF credit check — KICKOFF item 4 (the standing stop-rule)

Checked Nov 12, 2026 via the registered Hugging Face connector
(`hf_api.py`, account token, read-only calls) and HF's own billing
documentation (fetched the same day).

**Account, verified by `GET /api/whoami-v2`:** user `CardCauldronTCG`
(Sabastian Edward Caudill). Billing-relevant fields, verbatim from
the response:

- `canPay: true`
- `billingMode: "prepaid"`
- `isPro: false`
- billing `periodEnd`: Dec 1, 2026 (epoch 1796083200)
- Token scopes include `user.billing.read` and `job.write`.

**Usage this period, verified by `GET /api/settings/billing/usage-v2`
(Nov 1–13 window):** Jobs 0 minutes / $0, Endpoints $0, Inference
Providers $0, ZeroGPU $0. Nothing has been spent against the credit.

**What the credit can pay for** (HF billing doc, "Support FAQ"):
*"Credits let you use HF pay-as-you-go services: Jobs: run any
workload on GPUs · Inference Providers · Inference Endpoints · GPU
Spaces · ZeroGPU · Private Storage."* Subscription-style credits
*"are applied automatically before any pay-as-you-go usage is
billed."* HF Jobs specifically gate on a prepaid credit balance:
an account without prepaid credits gets HTTP 402 ("Hugging Face
Jobs need pre-paid credits") — jobs draw the balance down and stop
when it is exhausted; HF's own FAQ frames exhaustion as a *service
disruption* to avoid, i.e. the failure mode is the job stopping,
not a silent charge appearing from nowhere.

**The payment-method question — the stop-rule itself:**

> **Verdict: the credit is usable WITHOUT linking a payment method.
> The route does NOT die at KICKOFF item 4.**

Evidence: the account is *already* in `prepaid` billing mode with
`canPay: true` — that state exists today, with no action from us,
and no payment method has ever been linked by the crew (house rule:
linking one is the owner's tap only, never done for him). Jobs bill
against the prepaid balance; there is no step in the Jobs flow that
demands a card before a job can run against existing credit. The
Lexsi page's warning (*"Hugging Face may ask you to link a payment
method to redeem the coupon"* — `PLAN.md` §6) concerns *redeeming*
the coupon; per the owner's own Nov 3 record
(`PROBLEM-STATEMENTS-2026-11-03.md`) he already claimed the credits
via an email route, and the account's prepaid/canPay state today is
consistent with that redemption having landed.

**Two honest limits on this verdict:**

1. **The exact remaining balance is not exposed by any HF API
   endpoint reachable with this token** (billing overview/balance
   paths were probed; only usage is readable). The working figure
   is the owner's $20; Lexsi's published FAQ figure is $10
   (`PROBLEM-STATEMENTS-2026-11-03.md`). This protocol is budgeted
   to fit **even the $10 figure** (§5), and Gate G0 (§6) requires a
   human read-back of the balance at
   `huggingface.co/settings/billing` before the first job launches.
2. If *any* HF screen, at *any* point in the run, demands linking a
   payment method, the standing rule fires: **STOP, spend nothing,
   report.** Auto-recharge is never to be enabled (it requires a
   payment method by construction; with none on file there is
   nothing to recharge from, which is the safe configuration).

## 2. Weights route — trainable Aya Expanse 8B inside HF

The local bf16 safetensors were deleted Nov 9, 2026 (RUN-CONFIG);
only the Q4_K_M GGUF survives locally, and LoRA cannot train
against it. **No local re-download is needed at all:**

- The training job pulls the base model directly from the Hub:
  **`CohereLabs/aya-expanse-8b` @ commit
  `5062468bf9bc0c6035fd64e06274333ec127d980`** — the exact commit
  recorded in `baseline-run/RUN-CONFIG.json` as the baseline's
  source, so the tune starts from byte-identical weights to the
  ones the baseline GGUF was converted from.
- Verified via `GET /api/models/CohereLabs/aya-expanse-8b?blobs=true`
  (Nov 12): 4 safetensors shards totalling **16,056,095,672 B**
  (~16.06 GB bf16) + tokenizer (~12.8 MB) + config. Architecture
  `CohereForCausalLM`, 8B — `transformers`/`trl` load it natively.
- **Gating:** the repo reports `gated: "auto"`, licence
  **CC-BY-NC 4.0**. Read access for *this account* was verified
  live today: `config.json` fetched with the account token, and a
  weights shard request returned the signed-storage redirect
  (authorization passed — a denied gated repo returns 401/403, not
  a redirect). The saved token also carries the
  `canReadGatedRepos` fine-grained scope. **No owner click-through
  is outstanding.** Contingency, recorded now: if a job ever gets a
  403 on this repo, the fix is the owner's one-click "agree and
  access" on the repo page — owner-hands only, never clicked for
  him — and the run pauses until then.
- The job's ephemeral disk (≥110 GB on every candidate flavor, §5)
  holds the download + merged copy + GGUF with room to spare.
  Nothing 16 GB-sized transits the house machines in either
  direction except the finished Q4_K_M GGUF (~5.06 GB) coming home
  for the audit — the G1 has room; the VM (disk-quota history,
  RUN-CONFIG) is not used as the landing zone.

## 3. Dataset promotion path (Dataset B: DRAFT → training input)

`dataset-b-DRAFT.csv` is **never edited** (SHA-256
`0806fb47dfa0280550aa37aa61ed0bf23b88ae68ca9b0999be9cc1899e608f8d`,
re-verified Nov 12). Both fences passed Nov 12
(`dataset-b-FENCE-CHECKS-2026-11-12.md`: designated-fake 15/15,
spot-check 15/15 — crew packet; the status file's naming of
Sabastian/Latch as the formal spot-check sign-off is noted, and the
owner approved this route after receiving that report).

Promotion produces two new files; the draft stays as-is:

1. **`dataset-b.csv`** (same folder) — a byte-identical copy of the
   draft (the status file's "loses its DRAFT name" step). Verified
   by SHA-256 equality after copying.
2. **`dataset-b-TRAINING.jsonl`** (same folder) — the training
   input, built by a builder script `build_training_input.py`
   (written at run time, kept in this folder) that:
   - reads `dataset-b.csv` +
...[truncated 10327 chars]