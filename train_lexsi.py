#!/usr/bin/env python3
"""Lexsi AlignTune — LoRA fine-tune of CohereLabs/aya-expanse-8b.

Implements FINETUNE-PROTOCOL-2026-11-12.md exactly:
- base: CohereLabs/aya-expanse-8b @ 5062468bf9bc0c6035fd64e06274333ec127d980
  (the commit the Q4_K_M baseline GGUF was converted from)
- data: CardCauldronTCG/lexsi-dataset-b :: dataset-b-TRAINING.jsonl
  (18 prompt/completion pairs, baseline template, control row x4)
- recipe: TRL SFTTrainer + PEFT LoRA r16 / alpha32, all-linear,
  LR 1e-4 cosine, bf16, completion-only loss, checkpoints at 20/40/60
- each checkpoint: adapter pushed first, then merged + converted to
  Q4_K_M GGUF in-job and the GGUF pushed to
  CardCauldronTCG/aya-expanse-8b-lexsi-aligntune (push-before-polish:
  merged bf16 folders are pushed only while the time budget allows)

Modes: --mode smoke (2 steps, final adapter only, full merge+convert+
write path exercised) / --mode main (60 steps, checkpoints 20/40/60).

VOLUME MODE (v2, Nov 12): HF Jobs created through this house's
connector carry no usable in-job HF token (the connector's surrogate
is proxy-local; smoke job 6af5c1be proved LocalTokenNotFoundError, and
a secrets-passed surrogate is rejected by HF as an invalid token).
So the job runs fully token-free: the base model is mounted read-only
at /base (Volume revision pinned to the protocol commit), the
training data at /data, and all artifacts are written to the writable
bucket volume at /out. Publication to the artifact repo happens
afterwards from the house side, through the connector.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

BASE = "CohereLabs/aya-expanse-8b"
BASE_REV = "5062468bf9bc0c6035fd64e06274333ec127d980"
DATA_REPO = "CardCauldronTCG/lexsi-dataset-b"
OUT_REPO = "CardCauldronTCG/aya-expanse-8b-lexsi-aligntune"
LLAMA = os.environ.get("LLAMA_CPP_DIR", os.path.expanduser("~/llama.cpp"))
BASE_DIR = os.environ.get("LEXSI_BASE_DIR", "/base")
DATA_JSONL = os.environ.get("LEXSI_DATA_JSONL", "/data/dataset-b-TRAINING.jsonl")
OUT_DIR = os.environ.get("LEXSI_OUT_DIR", "/out")
WORK = os.path.expanduser("~/lexsi-work")

EXPECTED_PROMPT_TAIL = "<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def sh(cmd):
    log("+", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def template_check(tokenizer, sample_user_text):
    """The training render must reproduce the baseline GGUF-lane prompt
    (RUN-CONFIG): <BOS><|START_OF_TURN_TOKEN|><|USER_TOKEN|>{user}
    <|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>.
    llama.cpp supplied the BOS itself at inference; the chat template
    supplies it here. Abort loudly on any mismatch."""
    rendered = tokenizer.apply_chat_template(
        [{"role": "user", "content": sample_user_text}],
        tokenize=False, add_generation_prompt=True)
    bos = tokenizer.bos_token or ""
    body = rendered[len(bos):] if bos and rendered.startswith(bos) else rendered
    expected = ("<|START_OF_TURN_TOKEN|><|USER_TOKEN|>" + sample_user_text
                + EXPECTED_PROMPT_TAIL)
    ok = body == expected
    log("TEMPLATE_CHECK", "PASS" if ok else "FAIL")
    if not ok:
        log("RENDERED:", repr(rendered[:200]), "...", repr(rendered[-120:]))
        log("EXPECTED:", repr(expected[:200]), "...", repr(expected[-120:]))
        sys.exit(3)
    return rendered


def write_adapter(local_dir, step):
    dest = os.path.join(OUT_DIR, "adapters", f"checkpoint-{step}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(local_dir, dest)
    log(f"wrote adapter checkpoint-{step} -> {dest}")


def merge_convert_write(tokenizer, adapter_dir, step, write_merged):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    tag = f"checkpoint-{step}"
    merged_dir = os.path.join(WORK, f"merged-{step}")
    if os.path.exists(merged_dir):
        shutil.rmtree(merged_dir)
    log(f"[{tag}] loading base for merge")
    base = AutoModelForCausalLM.from_pretrained(
        BASE_DIR, torch_dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(base, adapter_dir)
    model = model.merge_and_unload()
    model.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    del model, base
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    q4 = os.path.join(WORK, f"ckpt-{step}-Q4_K_M.gguf")
    try:
        # Preferred: one-step K-quant conversion if this llama.cpp's
        # convert_hf_to_gguf.py supports --outtype q4_k_m.
        sh([sys.executable, os.path.join(LLAMA, "convert_hf_to_gguf.py"),
            merged_dir, "--outtype", "q4_k_m", "--outfile", q4])
    except subprocess.CalledProcessError:
        log(f"[{tag}] direct q4_k_m convert unsupported; f16 + quantize path")
        f16 = os.path.join(WORK, f"ckpt-{step}-f16.gguf")
        sh([sys.executable, os.path.join(LLAMA, "convert_hf_to_gguf.py"),
            merged_dir, "--outtype", "f16", "--outfile", f16])
        sh([os.path.join(LLAMA, "build", "bin", "llama-quantize"),
            f16, q4, "Q4_K_M"])
        os.remove(f16)
    gguf_dest = os.path.join(OUT_DIR, "gguf", tag,
                             "aya-expanse-8b-lexsi-Q4_K_M.gguf")
    os.makedirs(os.path.dirname(gguf_dest), exist_ok=True)
    shutil.copyfile(q4, gguf_dest)
    log(f"[{tag}] wrote GGUF ({os.path.getsize(q4)} bytes) -> {gguf_dest}")
    if write_merged:
        mdest = os.path.join(OUT_DIR, "merged", tag)
        if os.path.exists(mdest):
            shutil.rmtree(mdest)
        shutil.copytree(merged_dir, mdest)
        log(f"[{tag}] wrote merged bf16 -> {mdest}")
    shutil.rmtree(merged_dir, ignore_errors=True)
    return q4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "main"], default="main")
    args = ap.parse_args()
    t0 = time.time()
    os.makedirs(WORK, exist_ok=True)

    import torch
    from datasets import load_dataset

    log("volume mode: base at", BASE_DIR, "| data at", DATA_JSONL,
        "| out at", OUT_DIR)
    data_path = DATA_JSONL
    rows = [json.loads(l) for l in open(data_path) if l.strip()]
    log(f"training samples: {len(rows)}")
    assert len(rows) == 18, f"expected 18 samples, got {len(rows)}"

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(BASE_DIR)
    template_check(tokenizer, rows[0]["prompt"][0]["content"])

    ds = load_dataset("json", data_files=data_path, split="train")

    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer
    from transformers import AutoModelForCausalLM

    model = AutoModelForCausalLM.from_pretrained(
        BASE_DIR, torch_dtype=torch.bfloat16,
        attn_implementation="sdpa")
    model.config.use_cache = False

    peft_cfg = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0,
                          target_modules="all-linear", task_type="CAUSAL_LM")

    smoke = args.mode == "smoke"
    max_steps = 2 if smoke else 60
    soft_budget_min = 38 if smoke else 100  # merged-write budget guard

    cfg_kwargs = dict(
        output_dir=os.path.join(WORK, "trainer-out"),
        max_steps=max_steps,
        per_device_train_batch_size=6,
        gradient_accumulation_steps=1,
        learning_rate=1e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        logging_steps=1,
        save_strategy="no" if smoke else "steps",
        save_steps=20,
        save_total_limit=None,
        bf16=True,
        gradient_checkpointing=True,
        seed=42,
        report_to=[],
        packing=False,
    )
    try:
        cfg = SFTConfig(completion_only_loss=True, max_length=2048,
                        **cfg_kwargs)
    except TypeError:
        cfg = SFTConfig(max_seq_length=2048, **cfg_kwargs)
        log("SFTConfig: fell back to max_seq_length / default loss masking")

    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         peft_config=peft_cfg, processing_class=tokenizer)

    # Show one fully-tokenized training example for the log record.
    try:
        ex = trainer.train_dataset[0]
        ids = ex["input_ids"]
        log("EXAMPLE_DECODED_BEGIN")
        print(tokenizer.decode(ids)[:600], flush=True)
        log("EXAMPLE_DECODED_END",
            "ends_with_eot=", ids[-1] == tokenizer.convert_tokens_to_ids(
                "<|END_OF_TURN_TOKEN|>"))
    except Exception as e:  # never let the peek kill the run
        log("example peek failed:", repr(e))

    trainer.train()

    artifacts = []
    if smoke:
        final_dir = os.path.join(WORK, "adapter-final")
        trainer.save_model(final_dir)
        tokenizer.save_pretrained(final_dir)
        write_adapter(final_dir, step=2)
        artifacts.append("adapters/checkpoint-2")
        q4 = merge_convert_write(tokenizer, final_dir, step=2,
                                 write_merged=False)
        artifacts.append("gguf/checkpoint-2/aya-expanse-8b-lexsi-Q4_K_M.gguf")
    else:
        ckpts = []
        for step in (20, 40, 60):
            d = os.path.join(WORK, "trainer-out", f"checkpoint-{step}")
            assert os.path.isdir(d), f"missing trainer checkpoint {d}"
            ckpts.append((step, d))
        # write-before-polish: ALL adapters land before any merge work
        for step, d in ckpts:
            write_adapter(d, step)
            artifacts.append(f"adapters/checkpoint-{step}")
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        for step, d in ckpts:
            elapsed_min = (time.time() - t0) / 60
            write_merged = elapsed_min < soft_budget_min
            q4 = merge_convert_write(tokenizer, d, step, write_merged)
            artifacts.append(f"gguf/checkpoint-{step}/"
                               "aya-expanse-8b-lexsi-Q4_K_M.gguf")
            if write_merged:
                artifacts.append(f"merged/checkpoint-{step}")

    log("DONE " + json.dumps({"mode": args.mode,
                              "elapsed_min": round((time.time() - t0) / 60, 1),
                              "artifacts": artifacts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
