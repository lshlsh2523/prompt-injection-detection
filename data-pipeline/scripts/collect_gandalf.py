# scripts/collect_gandalf.py
# Gandalf ignore_instructions 원본(Lakera/gandalf_ignore_instructions)을
# raw/gandalf/에 그대로 저장한다.
#
# 성격:
#   Gandalf(비밀번호 방어 게임)에 실제 사용자가 제출한 프롬프트 중,
#   "Ignore all previous instructions"와의 임베딩 유사도가 0.825 이상인 것만
#   필터링해 모은 "실제(야생) 인젝션" 모음이다. 근사 중복 제거·PII 제거가 되어 있다.
#   → 순수 명령 덮어쓰기(injection) 유형. 우리 핵심 약점(인젝션) 보강의 1순위.
#
# split: train / validation / test (전체 약 1,000개를 80/10/10로 나눈 것,
#        표본별 독립 배정이라 정확히 8:1:1은 아님)
# 예상 컬럼: text (인젝션 프롬프트) — 스크립트가 실제 컬럼을 출력하니 확인할 것
# 라이선스: MIT
#
# 나중 라벨 계획 (clean_integrate 단계):
#   - 전 행 label = 1, attack_type = "injection", source = "gandalf"
#
# 주의(정제 단계에서 반영할 것):
#   - 소재가 "비밀번호 빼내기"에 편향돼 있다(기법은 injection이 맞고 주제만 쏠림).
#     정상 클래스에 password 관련 텍스트가 섞이지 않는지 교차 확인.
#   - 카드에도 명시: 자동 수집이라 소량의 노이즈(진짜 인젝션이 아닌 표본)가 있을 수 있음.
#   - Gandalf 계열의 다른 셋(gandalf_summarization 등)과 섞지 말 것. 여기선 ignore 계열만.

from datasets import load_dataset
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_DIR = SCRIPT_DIR.parent / "raw" / "gandalf"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print("[*] Gandalf (Lakera/gandalf_ignore_instructions) 다운로드 시작...")
ds = load_dataset("Lakera/gandalf_ignore_instructions")

print(f"[*] split 목록: {list(ds.keys())}")
for split_name, split_data in ds.items():
    print(f"    - {split_name}: {len(split_data)}행, 컬럼={split_data.column_names}")

total = 0
for split_name, split_data in ds.items():
    out_path = RAW_DIR / f"gandalf_{split_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in split_data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[+] 저장: {out_path.name} ({len(split_data)}행)")
    total += len(split_data)

print(f"[✓] 완료 — 총 {total}행 저장")