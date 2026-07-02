#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_integrate.py  (팀원 3 / task 3: 정제·통합)

6종 원본(raw/) -> 통합 스키마 1개 파일(processed/combined.jsonl)로 정제·통합한다.
하는 일 :  경량 클리닝 + 라벨 부여 + 대화 껍데기 제거 + 중복 제거 + 라벨 일관성 검사 + split 고정
안 하는 일: 클래스 균형(정상 다운샘플)  ->  이건 task 4에서. 여기 결과물은 '아직 불균형'이 정상이다.

출력:
  processed/combined.jsonl   7컬럼(id, text, label, source, split, attack_type, is_augmented)
  processed/build_report.md  검수용 리포트(출처×라벨 분포, 중복/충돌/제외 내역)

실행 (data-pipeline/ 에서, venv 켠 상태):
  python scripts/clean_integrate.py
"""

import json
import re
import random
from pathlib import Path
from collections import defaultdict, Counter

# ============================================================
# 설정 (바꿀 게 있으면 여기만 손대면 됨)
# ============================================================
BASE = Path(__file__).resolve().parent.parent      # data-pipeline/
RAW = BASE / "raw"
OUT = BASE / "processed"

SEED = 42            # split 재현용 고정 시드
TEST_RATIO = 0.20    # test 비율 (0.20 = 20%)

SCHEMA = ["id", "text", "label", "source", "split", "attack_type", "is_augmented"]

# 출처 처리 순서 = 중복 시 살아남을 우선순위(앞선 출처가 이김)
SOURCE_ORDER = ["deepset", "jailbreakbench", "advbench", "multijail", "prompts_chat", "hh_rlhf"]

# prompts.chat 오염 제외 목록 (act 컬럼 소문자 부분일치). 필요 시 추가.
PROMPTSCHAT_EXCLUDE = [
    "escape the box",   # "AI Trying to Escape the Box" (탈옥 프레이밍)
    "gaslighter",       # "Gaslighter" (조작)
]

# 존재해야 하는 raw 파일 (없으면 시작 전에 즉시 멈춤)
EXPECTED_FILES = [
    "deepset/deepset_train.jsonl",
    "deepset/deepset_test.jsonl",
    "prompts_chat/prompts_chat_train.jsonl",
    "advbench/advbench_train.jsonl",
    "jailbreakbench/jbb_behaviors_harmful.jsonl",
    "jailbreakbench/jbb_behaviors_benign.jsonl",
    "multijail/multijail_train.jsonl",
    "hh_rlhf/hh_rlhf_helpful_base_train.jsonl",
    "hh_rlhf/hh_rlhf_helpful_base_test.jsonl",
]


# ============================================================
# 유틸
# ============================================================
def read_jsonl(path):
    """JSONL을 한 줄씩 읽어 dict로 반환.
    주의: prompts.chat에 U+2028/U+2029(LS/PS) 특수 줄바꿈이 있어 .splitlines()나 .read()로
    통째 쪼개면 JSON이 깨진다. 물리적 줄(\\n) 단위로만 순회한다."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def light_clean(text):
    """BERT 호환 경량 클리닝.
    모든 공백류(스페이스·탭·개행·U+2028/2029 포함)를 단일 스페이스로 합치고 양끝을 제거한다.
    ※ 함정: 이 규칙은 개행 기반 인젝션 패턴(줄바꿈 여러 개로 지시를 끊는 등)의 '모양' 신호를
       지울 수 있다. 지금은 단순·일관을 우선했고, 필요하면 이 함수만 완화하면 된다."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def norm_for_dedup(text):
    """중복 판정용 정규화: 경량 클리닝 + 소문자화."""
    return light_clean(text).lower()


def first_human_turn(chosen):
    """hh-rlhf: "\\n\\nHuman: q1\\n\\nAssistant: a1\\n\\nHuman: q2 ..." 에서 첫 Human 질문만 추출.
    chosen/rejected는 질문이 동일하므로 chosen만 쓴다. 대화 껍데기(Human:/Assistant:)는 자동 제거됨."""
    if not chosen or "Human:" not in chosen:
        return None
    after = chosen.split("Human:", 1)[1]         # 첫 Human 뒤
    q = after.split("Assistant:", 1)[0]          # 다음 Assistant 전까지
    return q.strip() or None


# ============================================================
# 출처별 로더 -> (text, label, attack_type) 리스트 반환 (클리닝 전 원문)
# ============================================================
def load_deepset():
    rows = []
    for fn in ["deepset_train.jsonl", "deepset_test.jsonl"]:   # native split 무시하고 풀링
        for r in read_jsonl(RAW / "deepset" / fn):
            label = int(r["label"])                            # Deepset은 유일하게 라벨이 데이터에 있음(0·1)
            atype = "prompt_injection" if label == 1 else None
            rows.append((r["text"], label, atype))
    return rows


def load_advbench():
    # 컬럼: prompt, target -> prompt만 사용
    return [(r["prompt"], 1, "harmful_instruction")
            for r in read_jsonl(RAW / "advbench" / "advbench_train.jsonl")]


def load_jbb():
    rows = []
    for r in read_jsonl(RAW / "jailbreakbench" / "jbb_behaviors_harmful.jsonl"):
        rows.append((r["Goal"], 1, "harmful_instruction"))    # 대문자 Goal, Target 버림
    for r in read_jsonl(RAW / "jailbreakbench" / "jbb_behaviors_benign.jsonl"):
        rows.append((r["Goal"], 0, None))                     # benign -> 정상(0)
    return rows


def load_multijail():
    # en 컬럼만 사용 -> 공격(1). 나머지 언어 컬럼은 버림.
    return [(r["en"], 1, "harmful_instruction")
            for r in read_jsonl(RAW / "multijail" / "multijail_train.jsonl") if r.get("en")]


def load_hh_rlhf():
    rows = []
    for fn in ["hh_rlhf_helpful_base_train.jsonl", "hh_rlhf_helpful_base_test.jsonl"]:  # native split 무시
        for r in read_jsonl(RAW / "hh_rlhf" / fn):
            q = first_human_turn(r.get("chosen"))
            if q:
                rows.append((q, 0, None))                     # helpful 사람 질문 -> 정상(0)
    return rows


def load_prompts_chat():
    """type==TEXT만 + 오염 act 제외. 반환: (rows, excluded_act_names)"""
    rows, excluded = [], []
    for r in read_jsonl(RAW / "prompts_chat" / "prompts_chat_train.jsonl"):
        t = r.get("type")
        if t is not None and str(t).upper() != "TEXT":        # STRUCTURED/IMAGE 제외
            continue
        act = str(r.get("act", "")).lower()
        if any(bad in act for bad in PROMPTSCHAT_EXCLUDE):     # 오염 샘플 제외 + 플래그
            excluded.append(r.get("act", ""))
            continue
        prompt = r.get("prompt")
        if prompt:
            rows.append((prompt, 0, None))                    # 역할극 정상 프롬프트 -> 정상(0)
    return rows, excluded


# ============================================================
# 메인 파이프라인
# ============================================================
def preflight():
    missing = [f for f in EXPECTED_FILES if not (RAW / f).exists()]
    if missing:
        print("[에러] 다음 raw 파일이 없습니다. 파일명/경로를 확인하세요:")
        for m in missing:
            print("   -", RAW / m)
        raise SystemExit(1)


def main():
    preflight()
    OUT.mkdir(exist_ok=True)

    # 1) 수집 + 경량 클리닝 --------------------------------------------------
    raw_rows = []            # dict: text, label, source, attack_type
    per_source_loaded = {}   # 출처별 원본 행 수(클리닝 후)
    excluded_pc = []

    for src in SOURCE_ORDER:
        if src == "deepset":
            rows = load_deepset()
        elif src == "jailbreakbench":
            rows = load_jbb()
        elif src == "advbench":
            rows = load_advbench()
        elif src == "multijail":
            rows = load_multijail()
        elif src == "prompts_chat":
            rows, excluded_pc = load_prompts_chat()
        elif src == "hh_rlhf":
            rows = load_hh_rlhf()
        else:
            continue

        cnt = 0
        for text, label, atype in rows:
            cleaned = light_clean(text)
            if not cleaned:                 # 빈 텍스트 제거
                continue
            raw_rows.append({"text": cleaned, "label": label,
                             "source": src, "attack_type": atype})
            cnt += 1
        per_source_loaded[src] = cnt

    # 2) 중복 제거 + 라벨 일관성 검사 ----------------------------------------
    #    정규화 텍스트로 그룹핑. 한 그룹에 라벨이 2종 이상이면 '충돌' -> 전부 제외 + 플래그.
    #    같은 라벨이면 SOURCE_ORDER상 먼저 온 1개만 남김.
    groups = defaultdict(list)
    for row in raw_rows:
        groups[norm_for_dedup(row["text"])].append(row)

    kept, conflicts, dup_removed = [], [], 0
    for key, members in groups.items():
        labels = {m["label"] for m in members}
        if len(labels) > 1:
            conflicts.append(members)           # 라벨 충돌 -> 자동 삭제 금지, 전부 빼서 검토
            continue
        kept.append(members[0])                 # 같은 라벨 중복 -> 첫 출처 1개만
        dup_removed += len(members) - 1

    # 3) id / is_augmented 부여 ---------------------------------------------
    for i, row in enumerate(kept):
        row["id"] = f"{row['source']}_{i:06d}"
        row["is_augmented"] = False             # 증강은 train에만, 나중 단계. 지금은 전부 False

    # 4) split 고정 (source×label 층화, 고정 시드) --------------------------
    rng = random.Random(SEED)
    by_group = defaultdict(list)
    for row in kept:
        by_group[(row["source"], row["label"])].append(row)
    for _, members in by_group.items():
        rng.shuffle(members)
        n_test = round(len(members) * TEST_RATIO)
        for j, row in enumerate(members):
            row["split"] = "test" if j < n_test else "train"

    # 5) 저장 ----------------------------------------------------------------
    out_path = OUT / "combined.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for row in kept:
            f.write(json.dumps({k: row[k] for k in SCHEMA}, ensure_ascii=False) + "\n")

    # 6) 리포트 --------------------------------------------------------------
    write_report(kept, conflicts, dup_removed, excluded_pc, per_source_loaded)
    print(f"\n[완료] {out_path}  ({len(kept)}개)")
    print(f"[완료] {OUT/'build_report.md'}  (검수 리포트)")


def write_report(kept, conflicts, dup_removed, excluded_pc, per_source_loaded):
    total = len(kept)
    n_pos = sum(1 for r in kept if r["label"] == 1)
    n_neg = total - n_pos
    by_sl = Counter((r["source"], r["label"]) for r in kept)
    by_spl = Counter((r["split"], r["label"]) for r in kept)
    n_conflict_rows = sum(len(c) for c in conflicts)

    L = []
    L.append("# 정제·통합 리포트 (task 3)\n")
    L.append("> 클래스 균형(다운샘플)은 task 4에서 함. 아래 정상:공격 불균형은 **의도된 중간 상태**다.\n")

    L.append("## 요약\n")
    L.append(f"- 최종 유효 샘플: **{total}**개  (정상 0 = {n_neg} / 공격 1 = {n_pos})\n")
    ratio = (n_neg / n_pos) if n_pos else float('inf')
    L.append(f"- 정상:공격 비율 = **{ratio:.1f} : 1**  (불균형 정상 — task 4에서 조정)\n")
    L.append(f"- 같은 라벨 중복 제거: {dup_removed}개\n")
    L.append(f"- 라벨 충돌로 제외: {n_conflict_rows}개 ({len(conflicts)}그룹) — **팀 검토 필요**\n")
    L.append(f"- prompts.chat 오염 제외: {len(excluded_pc)}개\n")

    L.append("\n## 출처별 로드→최종 (중복/충돌 제거 전후)\n")
    L.append("| 출처 | 클리닝 후 로드 | 최종(정상0) | 최종(공격1) |\n|---|---|---|---|\n")
    for src in SOURCE_ORDER:
        L.append(f"| {src} | {per_source_loaded.get(src,0)} | "
                 f"{by_sl.get((src,0),0)} | {by_sl.get((src,1),0)} |\n")

    L.append("\n## split × 라벨 분포\n")
    L.append("| split | 정상0 | 공격1 |\n|---|---|---|\n")
    for sp in ["train", "test"]:
        L.append(f"| {sp} | {by_spl.get((sp,0),0)} | {by_spl.get((sp,1),0)} |\n")

    if excluded_pc:
        L.append("\n## prompts.chat 제외 목록 (act)\n")
        for a in excluded_pc:
            L.append(f"- {a}\n")

    if conflicts:
        L.append("\n## 라벨 충돌 샘플 (최대 10건, 검토용)\n")
        L.append("같은 텍스트가 서로 다른 출처에서 정상/공격으로 라벨됨 → 전부 제외함.\n\n")
        for members in conflicts[:10]:
            srcs = ", ".join(f"{m['source']}={m['label']}" for m in members)
            snippet = members[0]["text"][:120].replace("\n", " ")
            L.append(f"- [{srcs}] {snippet}\n")

    (OUT / "build_report.md").write_text("".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()