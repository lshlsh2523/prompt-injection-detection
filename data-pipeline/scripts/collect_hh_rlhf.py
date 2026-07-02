# scripts/collect_hh_rlhf.py
# Anthropic hh-rlhf의 helpful-base 서브셋만 raw/hh_rlhf/에 그대로 저장한다.
#
# 중요: hh-rlhf는 서브셋(data_dir)이 여러 개다.
#   - helpful-base / helpful-online / helpful-rejection-sampled : 정상 대화 (우리는 base만)
#   - harmless-base / red-team-attempts : 질문 자체가 공격성 → 정상(0)에 넣으면 안 됨. 받지 않는다.
# 우리는 helpful-base만 받아 정상(0) 샘플의 출처로 쓴다.
#
# 각 행 구조:
#   chosen:   "\n\nHuman: [질문] \n\nAssistant: [좋은 답변]"
#   rejected: "\n\nHuman: [질문] \n\nAssistant: [나쁜 답변]"
#   → chosen/rejected는 답변만 다르고 질문은 같다. 우리는 "질문"만 필요.
#     Human: 뒤 질문 추출은 정제 단계에서. 오늘은 원본 그대로 저장만.

from datasets import load_dataset
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "hh_rlhf"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] Anthropic/hh-rlhf (helpful-base 서브셋) 다운로드 시작...")
# data_dir로 서브셋 지정 — 이게 없으면 전체(harmless/red-team 포함)를 받아버린다
ds = load_dataset("Anthropic/hh-rlhf", data_dir="helpful-base")

print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"hh_rlhf_helpful_base_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")