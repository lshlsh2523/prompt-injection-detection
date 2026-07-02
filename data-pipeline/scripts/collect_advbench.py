# scripts/collect_advbench.py
# AdvBench (walledai/AdvBench) 원본을 raw/advbench/에 그대로 저장한다.

from datasets import load_dataset
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "advbench"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] AdvBench (walledai/AdvBench) 다운로드 시작...")
ds = load_dataset("walledai/AdvBench")

print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"advbench_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")