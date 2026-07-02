#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
balance_classes.py  (task 4: 클래스 균형 — 1:1)

processed/combined.jsonl 을 읽어 정상:공격 = 1:1 로 맞춘다.
- 공격(1)은 전부 보존, 정상(0)만 다운샘플.
- 다운샘플은 '출처 층화 비례' — 각 출처 비율을 유지해 prompts.chat 역할극(하드 네거티브)이
  증발하지 않게 한다.
- train / test 각 split을 따로 균형(데이터 누수 방지, split 규율 유지).
- 증강(공격 보강)은 여기서 안 함 -> is_augmented 전부 False 그대로. 증강은 train-only, 이후 단계.

출력:
  processed/balanced.jsonl      (7컬럼 스키마 동일, combined 의 부분집합)
  processed/balance_report.md   (전/후 분포, 출처별 잔존량)

실행 (data-pipeline/ 에서, 새 터미널이면 앞 3줄 먼저):
  # cd .../data-pipeline
  # source venv/Scripts/activate
  # export HF_HOME="$(pwd)/.hf_cache"
  python scripts/balance_classes.py
"""

import json
import random
from pathlib import Path
from collections import defaultdict, Counter

BASE = Path(__file__).resolve().parent.parent
COMBINED = BASE / "processed" / "combined.jsonl"
OUT = BASE / "processed" / "balanced.jsonl"
REPORT = BASE / "processed" / "balance_report.md"

# ---------- 설정 ----------
SEED = 42
NORMAL_PER_ATTACK = 1     # 정상:공격 비율. 1 = 1:1. 2로 바꾸면 2:1(정상 더 남김, 학습 시 클래스 가중치 필요)
BALANCE_TEST = True       # True면 test도 1:1. False면 test는 원본 분포 유지(현실적 평가용)
SCHEMA = ["id", "text", "label", "source", "split", "attack_type", "is_augmented"]


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def proportional_targets(source_counts, total_target):
    """각 출처 개수 비율대로 total_target 을 배분. 반올림 오차는 큰 출처부터 보정.
    각 출처가 가진 수를 넘겨 배정하지 않는다."""
    total = sum(source_counts.values())
    if total == 0 or total_target <= 0:
        return {s: 0 for s in source_counts}

    targets = {s: int(round(total_target * c / total)) for s, c in source_counts.items()}
    for s in targets:                                   # 가진 것보다 많이 요구 금지
        targets[s] = min(targets[s], source_counts[s])

    # 합을 total_target 에 정확히 맞춤(반올림으로 생긴 부족/초과분 보정)
    diff = total_target - sum(targets.values())
    order = sorted(source_counts, key=lambda s: source_counts[s], reverse=True)
    i = guard = 0
    while diff != 0 and guard < 100000:
        s = order[i % len(order)]
        if diff > 0 and targets[s] < source_counts[s]:
            targets[s] += 1
            diff -= 1
        elif diff < 0 and targets[s] > 0:
            targets[s] -= 1
            diff += 1
        i += 1
        guard += 1
    return targets


def balance_split(rows, rng, do_balance):
    """한 split 내에서 정상 다운샘플. rows: 해당 split의 모든 dict."""
    attacks = [r for r in rows if int(r["label"]) == 1]
    normals = [r for r in rows if int(r["label"]) == 0]

    if not do_balance:
        return attacks + normals                        # 균형 안 함(원본 유지)

    target_normal = len(attacks) * NORMAL_PER_ATTACK

    by_src = defaultdict(list)                           # 출처별 정상 그룹
    for r in normals:
        by_src[r["source"]].append(r)
    src_counts = {s: len(v) for s, v in by_src.items()}

    if sum(src_counts.values()) <= target_normal:        # 정상이 목표보다 적으면 다 씀
        return attacks + normals

    targets = proportional_targets(src_counts, target_normal)
    kept_normal = []
    for s, grp in by_src.items():
        k = targets[s]
        kept_normal.extend(grp if k >= len(grp) else rng.sample(grp, k))

    return attacks + kept_normal


def main():
    rows = list(load_jsonl(COMBINED))
    rng = random.Random(SEED)

    by_split = defaultdict(list)
    for r in rows:
        by_split[r["split"]].append(r)

    balanced = []
    for split in ["train", "test"]:
        do_bal = True if split == "train" else BALANCE_TEST
        balanced.extend(balance_split(by_split.get(split, []), rng, do_bal))

    # train/test 외 예상치 못한 split 이 있으면 그대로 통과(방어)
    for split, srows in by_split.items():
        if split not in ("train", "test"):
            balanced.extend(srows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in balanced:
            f.write(json.dumps({k: r[k] for k in SCHEMA}, ensure_ascii=False) + "\n")

    write_report(rows, balanced)
    print(f"[완료] {OUT}  ({len(balanced)}개)")
    print(f"[완료] {REPORT}")


def write_report(before, after):
    b = Counter((r["split"], int(r["label"])) for r in before)
    a = Counter((r["split"], int(r["label"])) for r in after)
    before_norm_src = Counter(r["source"] for r in before if int(r["label"]) == 0)
    after_norm_src = Counter(r["source"] for r in after if int(r["label"]) == 0)

    L = []
    L.append("# 클래스 균형 리포트 (task 4)\n")
    L.append(f"> 정상:공격 = {NORMAL_PER_ATTACK}:1 목표. 공격 전량 보존, 정상만 출처 층화 다운샘플. "
             f"BALANCE_TEST={BALANCE_TEST}.\n")

    L.append("\n## split × 라벨: 전 → 후\n")
    L.append("| split | 라벨 | 전 | 후 |\n|---|---|---|---|\n")
    for split in ["train", "test"]:
        for lab in [0, 1]:
            name = "정상0" if lab == 0 else "공격1"
            L.append(f"| {split} | {name} | {b.get((split, lab), 0)} | {a.get((split, lab), 0)} |\n")

    L.append("\n## 정상(0) 출처별 잔존: 전 → 후 (하드 네거티브 보존 확인)\n")
    L.append("| 출처 | 전 | 후 |\n|---|---|---|\n")
    for s in sorted(before_norm_src, key=lambda x: before_norm_src[x], reverse=True):
        L.append(f"| {s} | {before_norm_src[s]} | {after_norm_src.get(s, 0)} |\n")

    n_pos = sum(1 for r in after if int(r["label"]) == 1)
    n_neg = len(after) - n_pos
    L.append(f"\n## 최종\n")
    L.append(f"- 총 {len(after)}개 (정상 {n_neg} / 공격 {n_pos})\n")
    L.append("- 증강(공격 보강) 미실시 — is_augmented 전부 False. 적대적 증강은 이후 train-only 단계.\n")

    REPORT.write_text("".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()