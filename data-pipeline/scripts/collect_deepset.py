# scripts/collect_deepset.py
# Deepset Prompt Injections 원본을 raw/deepset/에 그대로 저장한다.

from datasets import load_dataset
from pathlib import Path
import json

# 이 스크립트 파일 기준으로 경로를 잡는다 (어디서 실행하든 동일하게 동작)
SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "deepset"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] Deepset Prompt Injections 다운로드 시작...")
ds = load_dataset("deepset/prompt-injections")

# 데이터셋 구조 확인용 출력
print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

# 원본을 split별로 JSONL로 저장 (한 줄에 샘플 하나)
total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"deepset_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")