# scripts/collect_prompts_chat.py
# prompts.chat (fka/prompts.chat) 원본을 raw/prompts_chat/에 그대로 저장한다.

from datasets import load_dataset
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "prompts_chat"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] prompts.chat (fka/prompts.chat) 다운로드 시작...")
ds = load_dataset("fka/prompts.chat")

print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

# 참고: type 컬럼에 어떤 값들이 있는지만 확인 (필터링은 하지 않음, 정제 단계 참고용)
if "type" in ds["train"].column_names:
    type_values = set(ds["train"]["type"])
    print(f"[*] type 컬럼 값 종류: {type_values}")

total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"prompts_chat_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")