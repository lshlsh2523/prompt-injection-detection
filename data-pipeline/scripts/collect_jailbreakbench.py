# scripts/collect_jailbreakbench.py
# JailbreakBench 공식 원본(JailbreakBench/JBB-Behaviors)의 behaviors subset을
# raw/jailbreakbench/에 그대로 저장한다.
#
# behaviors subset은 두 split으로 나뉜다:
#   - harmful (100행) : 순수 유해 요청 → label 1 후보
#   - benign  (100행) : 위험 주제지만 정상 요청(XS-Test 기반) → label 0 후보
#
# judge_comparison subset은 받지 않는다:
#   그 안의 prompt는 GCG/PAIR로 이미 "변형된" 탈옥 문자열이라,
#   표준 학습에 넣으면 적대적 증강 비교 실험이 오염된다.
#   (필요하면 나중에 난독화 평가셋 후보로 별도 검토)

from datasets import load_dataset
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "jailbreakbench"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] JailbreakBench/JBB-Behaviors (behaviors subset) 다운로드 시작...")
# 두 번째 인자 "behaviors"가 subset(config) 지정
ds = load_dataset("JailbreakBench/JBB-Behaviors", "behaviors")

print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"jbb_behaviors_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")