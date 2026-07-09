# scripts/collect_xtram1.py
# safe-guard-prompt-injection 원본(xTRam1/safe-guard-prompt-injection)을
# raw/xtram1/에 그대로 저장한다.
#
# 성격:
#   GPT-3.5-turbo로 카테고리 트리 구조를 따라 생성한 합성 인젝션 데이터셋.
#   공격(label 1) 약 3,000개가 context manipulation / social engineering /
#   ignore prompt / fake completion 등 여러 인젝션 카테고리를 커버한다.
#   → 인젝션 "다양성" 보강용. deepset 260개의 종류 편중을 메우는 게 목적.
#
# split: train / test
# 예상 컬럼: text, label (0=정상/safe, 1=공격/injection)
#           — 스크립트가 실제 컬럼을 출력하니 확인할 것
#
# 나중 라벨 계획 (clean_integrate 단계):
#   - 원본 label을 그대로 사용(1=공격, 0=정상). attack_type: label 1 → "injection".
#   - source = "xtram1"
#   - 역할극/페르소나 샘플은 원본에서 label 0으로 되어 있어 우리 규칙(정당한 역할극=0)과 일치.
#
# ★ 반드시 정제 단계에서 처리할 위험 (수집 조사에서 확인됨):
#   1) 씨앗 오염: 이 데이터셋은 fka/awesome-chatgpt-prompts(= 우리 prompts.chat, label 0)와
#      jackhhao/jailbreak-classification을 "시드"로 만들어졌다.
#      → prompts.chat 및 (쓸 경우) jackhhao와의 교차 중복 제거가 필수.
#         source 컬럼으로 근거를 남길 것.
#   2) 합성 템플릿 흔적: GPT-3.5 생성이라 label 1에 유사 템플릿 반복이 있을 수 있다.
#      → 정규화 후 완전일치 dedup + (여유되면) 근사 중복 점검.
#   3) 정상(label 0) 약 7,000개는 우리 정상 분포(hh-rlhf, prompts.chat)와 성격이 달라
#      전량 사용할 필요 없음. 클래스 균형 단계에서 선별.
#
# 참고: jayavibhav/prompt-injection(327K)은 이 데이터셋을 통째로 포함한 확장본이다.
#       둘을 함께 쓰면 대량 중복이 생기므로 xTRam1만 사용한다.

from datasets import load_dataset
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "xtram1"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] safe-guard-prompt-injection (xTRam1/safe-guard-prompt-injection) 다운로드 시작...")
ds = load_dataset("xTRam1/safe-guard-prompt-injection")

print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"xtram1_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")