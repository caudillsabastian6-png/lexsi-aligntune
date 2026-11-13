#!/usr/bin/env python3
"""Lexsi AlignTune — local HF driver (house connector pattern).

Runs on the custom.huggingface dynamic-credential surrogate; the real
token is swapped in at egress and never printed or written to disk here.

Subcommands:
  prep             create dataset+model repos, upload training files
  submit smoke|main  fire the HF Job (l4x1 smoke / a10g-large main)
  status <job_id>  inspect a job
  logs <job_id>    fetch job logs (tail)
  cancel <job_id>  cancel a job
  usage            read back this period's billing usage
"""
import json
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_REPO = "CardCauldronTCG/lexsi-dataset-b"
OUT_REPO = "CardCauldronTCG/aya-expanse-8b-lexsi-aligntune"
IMAGE = "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel"

BUCKET = "CardCauldronTCG/lexsi-aligntune-out"
BASE_REPO = "CohereLabs/aya-expanse-8b"
BASE_REV = "5062468bf9bc0c6035fd64e06274333ec127d980"

BOOTSTRAP = r"""
set -euxo pipefail
export LLAMA_CPP_DIR=$HOME/llama.cpp
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq git cmake g++ make
which git cmake g++
pip install -q --no-cache-dir "transformers>=4.46,<4.50" "trl>=0.12,<0.14" \
  "peft>=0.13,<0.16" "accelerate>=1.0,<1.2" "datasets>=2.19,<3.4" \
  "huggingface_hub>=0.26" safetensors sentencepiece gguf protobuf
git clone --depth 1 https://github.com/ggerganov/llama.cpp $LLAMA_CPP_DIR
test -f $LLAMA_CPP_DIR/convert_hf_to_gguf.py
cmake -S $LLAMA_CPP_DIR -B $LLAMA_CPP_DIR/build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DLLAMA_CURL=OFF >/dev/null
cmake --build $LLAMA_CPP_DIR/build --target llama-quantize -j $(nproc)
ls /base /data
python3 /data/train_lexsi.py --mode {mode}
"""


TOKEN = None


def api():
    global TOKEN
    entry = dynamic_credential_entry("custom.huggingface")
    from huggingface_hub import HfApi
    TOKEN = entry["surrogate"]
    return HfApi(token=TOKEN)


def prep(a):
    who = a.whoami()
    assert who.get("name") == "CardCauldronTCG", who.get("name")
    print(a.create_repo(DATA_REPO, repo_type="dataset", exist_ok=True,
                        private=False))
    print(a.create_repo(OUT_REPO, repo_type="model", exist_ok=True,
                        private=False))
    for f in ("dataset-b-TRAINING.jsonl", "train_lexsi.py",
              "build_training_input.py", "dataset-b.csv"):
        r = a.upload_file(path_or_fileobj=os.path.join(HERE, f),
                          path_in_repo=f, repo_id=DATA_REPO,
                          repo_type="dataset",
                          commit_message=f"Lexsi AlignTune: {f}")
        print("uploaded", f, "->", r)
    try:
        b = a.create_bucket(BUCKET, private=True, exist_ok=True)
        print("bucket:", b)
    except Exception as e:
        print("bucket create note:", type(e).__name__, str(e)[:200])
    return 0


def submit(a, mode, flavor_override=None):
    if mode == "smoke":
        flavor, timeout = flavor_override or "l4x1", 45 * 60
    else:
        flavor, timeout = flavor_override or "a10g-large", 120 * 60
    from huggingface_hub import Volume
    volumes = [
        Volume(type="model", source=BASE_REPO, revision=BASE_REV,
               mount_path="/base"),
        Volume(type="dataset", source=DATA_REPO, mount_path="/data"),
        Volume(type="bucket", source=BUCKET, mount_path="/out"),
    ]
    job = a.run_job(
        image=IMAGE,
        command=["bash", "-lc", BOOTSTRAP.replace("{mode}", mode)],
        flavor=flavor,
        timeout=timeout,
        env={"TOKENIZERS_PARALLELISM": "false"},
        volumes=volumes,
        token=TOKEN,
        labels={"project": "lexsi-aligntune", "mode": mode},
    )
    print(json.dumps({"job_id": job.id, "status": str(job.status),
                      "flavor": flavor, "mode": mode}, indent=1))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    a = api()
    if cmd == "prep":
        return prep(a)
    if cmd == "submit":
        return submit(a, sys.argv[2],
                      sys.argv[3] if len(sys.argv) > 3 else None)
    if cmd == "status":
        j = a.inspect_job(job_id=sys.argv[2])
        print(json.dumps({"id": j.id, "status": str(j.status),
                          "flavor": str(getattr(j, "flavor", "")),
                          "created": str(getattr(j, "created_at", "")),
                          "stage": str(getattr(j, "stage", ""))}, indent=1))
        return 0
    if cmd == "logs":
        lines = list(a.fetch_job_logs(job_id=sys.argv[2]))
        tail = int(sys.argv[3]) if len(sys.argv) > 3 else 120
        print("\n".join(lines[-tail:]))
        return 0
    if cmd == "cancel":
        a.cancel_job(job_id=sys.argv[2])
        print("cancelled", sys.argv[2])
        return 0
    if cmd == "fetch-out":
        dest = sys.argv[2]
        os.makedirs(dest, exist_ok=True)
        tree = a.list_bucket_tree(BUCKET, recursive=True)
        paths = []
        for item in tree:
            p = getattr(item, "path", None)
            if p:
                paths.append(p)
                print("bucket:", p,
                      getattr(item, "size", ""))
        want = [p for p in paths if p.endswith(".gguf")
                or "/adapters/" in p]
        if want:
            a.download_bucket_files(BUCKET, files=want, local_dir=dest)
            print("downloaded", len(want), "files to", dest)
        return 0
    if cmd == "usage":
        import datetime
        s = int(datetime.datetime(2026, 11, 1,
              tzinfo=datetime.timezone.utc).timestamp())
        e = int(datetime.datetime(2026, 12, 1,
              tzinfo=datetime.timezone.utc).timestamp())
        import urllib.request
        from dynamic_credentials import add_surrogate_to_request, \
            read_json_response
        url = (f"https://huggingface.co/api/settings/billing/"
               f"usage-v2?startDate={s}&endDate={e}")
        req = urllib.request.Request(url)
        add_surrogate_to_request(req, "custom.huggingface",
                                 allowed_hosts=["huggingface.co"])
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(json.dumps(read_json_response(resp), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
