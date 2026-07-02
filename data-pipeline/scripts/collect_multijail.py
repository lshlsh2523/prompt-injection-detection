# scripts/collect_multijail.py
# MultiJail 공식 원본(DAMO-NLP-SG/MultiJail)을 raw/multijail/에 그대로 저장한다.
#
# 이 데이터셋은 315개 영어 유해 질문을 9개 언어로 번역한 "병렬" 구조다.
# 한 행에 같은 뜻이 여러 언어 컬럼(en, zh, it, vi, ar, ko, th, bn, sw, jv)으로 들어있다.
# 우리는 en 컬럼(영어 유해 질문 315개)만 label 1로 쓸 것이다.
#
# (en 315개 중 300개가 Anthropic red-team 출신이라 AdvBench/JBB와 중복 가능 → 정제 시 제거 대상)

from datasets import load_dataset
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "multijail"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] MultiJail (DAMO-NLP-SG/MultiJail) 다운로드 시작...")
ds = load_dataset("DAMO-NLP-SG/MultiJail")

print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"multijail_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")