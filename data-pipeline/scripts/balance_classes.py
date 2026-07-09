#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
balance_classes.py  (task 4: 클래스 균형)

processed/combined_final.jsonl 을 읽어 정상:공격 비율을 맞춘다.
  - train: 정상:공격 = NORMAL_PER_ATTACK : 1  (기본 2:1)
  - test : 1:1 (BALANCE_TEST=True) — 정밀도/재현율 해석을 깔끔히, 2주차 베이스라인과 비교 가능
  - 공격(1)은 전부 보존, 정상(0)만 '출처 층화 비례'로 다운샘플
    (각 출처 비율 유지 → prompts.chat 역할극 같은 하드 네거티브가 증발하지 않게)
  - train / test 각 split을 따로 균형(누수 방지, split 규율 유지)
  - 증강은 여기서 안 함 → is_augmented 전부 False. 적대적 증강은 이후 train-only 단계.

입력 주의:
  파이프라인 순서상 입력은 combined_final.jsonl 이다.
    combined.jsonl → [안티조인] combined_clean.jsonl → [test 근사중복 제거] combined_final.jsonl → [balance]
  combined.jsonl / combined_clean.jsonl 을 쓰면 이미 제거한 오염/누수가 되살아난다.

출력:
  processed/balanced.jsonl      (7컬럼 스키마 동일, 입력의 부분집합)
  processed/balance_report.md   (전/후 분포, 출처별 잔존량, balance 후 길이 지름길 실측)

실행 (data-pipeline/ 에서):
  python scripts/balance_classes.py            # 실행
  python scripts/balance_classes.py --selftest # 로직 검증
"""

import sys
import json
import random
import statistics as st
from pathlib import Path
from collections import defaultdict, Counter

BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "processed" / "combined_final.jsonl"     # ← 파이프라인 최종 입력
OUT = BASE / "processed" / "balanced.jsonl"
REPORT = BASE / "processed" / "balance_report.md"

# ---------- 설정 ----------
SEED = 42
NORMAL_PER_ATTACK = 2     # train 정상:공격 비율. 2 = 2:1(정상을 넉넉히 남겨 과탐 억제·다양성 유지)
BALANCE_TEST = True       # True면 test는 1:1
SCHEMA = ["id", "text", "label", "source", "split", "attack_type", "is_augmented"]


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def proportional_targets(source_counts, total_target):
    """각 출처 개수 비율대로 total_target 을 배분. 각 출처가 가진 수를 넘겨 배정하지 않는다."""
    total = sum(source_counts.values())
    if total == 0 or total_target <= 0:
        return {s: 0 for s in source_counts}

    targets = {s: int(round(total_target * c / total)) for s, c in source_counts.items()}
    for s in targets:
        targets[s] = min(targets[s], source_counts[s])

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


def balance_split(rows, rng, do_balance, ratio):
    """한 split 내에서 정상 다운샘플. rows: 해당 split의 모든 dict."""
    attacks = [r for r in rows if int(r["label"]) == 1]
    normals = [r for r in rows if int(r["label"]) == 0]

    if not do_balance:
        return attacks + normals

    target_normal = len(attacks) * ratio

    by_src = defaultdict(list)
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


def length_shortcut_accuracy(rows):
    """길이 하나(단일 임계값)로 얻는 최대 balanced accuracy vs 우연(50%).
    balanced accuracy = (공격 맞힌 비율 + 정상 맞힌 비율)/2 — 클래스 비율에 안 휘둘린다.
    반환: (best_balacc, 0.5, rule)  — 50%보다 크게 높으면 길이가 정보를 준다는 뜻."""
    data = sorted(((len(r["text"]), int(r["label"])) for r in rows), key=lambda x: x[0])
    n = len(data)
    n_attack = sum(lab for _, lab in data)
    n_normal = n - n_attack
    if n == 0 or n_attack == 0 or n_normal == 0:
        return 0.5, 0.5, "-"

    best, best_rule = 0.5, "임계값 무의미"
    left_attack = left_total = 0
    for i in range(n + 1):
        la = left_attack                      # 왼쪽(len<t) 공격
        ln = left_total - left_attack         # 왼쪽 정상
        ra = n_attack - la                    # 오른쪽(len>=t) 공격
        rn = n_normal - ln                    # 오른쪽 정상
        bal_long = (ra / n_attack + ln / n_normal) / 2     # 길면 공격
        bal_short = (la / n_attack + rn / n_normal) / 2    # 짧으면 공격
        if bal_long > best:
            best, best_rule = bal_long, f">= {data[i][0] if i < n else '∞'}자면 공격"
        if bal_short > best:
            best, best_rule = bal_short, f"< {data[i][0] if i < n else '∞'}자면 공격"
        if i < n:
            left_total += 1
            left_attack += data[i][1]
    return best, 0.5, best_rule


def main():
    if not INPUT.exists():
        print(f"[에러] 입력 없음: {INPUT}")
        print(">> test 근사중복 제거(dedup_test_neardup.py)까지 끝나 combined_final.jsonl 이 있어야 함.")
        sys.exit(1)

    rows = list(load_jsonl(INPUT))
    rng = random.Random(SEED)

    by_split = defaultdict(list)
    for r in rows:
        by_split[r["split"]].append(r)

    balanced = []
    for split in ["train", "test"]:
        do_bal = True if split == "train" else BALANCE_TEST
        ratio = NORMAL_PER_ATTACK if split == "train" else 1     # test는 1:1
        balanced.extend(balance_split(by_split.get(split, []), rng, do_bal, ratio))

    for split, srows in by_split.items():                        # 예상 밖 split 방어
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
    L.append("# 클래스 균형 리포트 (task 4)\n\n")
    L.append(f"> 입력: combined_final.jsonl / train 정상:공격 = {NORMAL_PER_ATTACK}:1, "
             f"test 1:1(BALANCE_TEST={BALANCE_TEST}) / 공격 전량 보존, 정상만 출처 층화 다운샘플.\n")

    L.append("\n## split × 라벨: 전 → 후\n\n")
    L.append("| split | 라벨 | 전 | 후 |\n|---|---|---|---|\n")
    for split in ["train", "test"]:
        for lab in [0, 1]:
            name = "정상0" if lab == 0 else "공격1"
            L.append(f"| {split} | {name} | {b.get((split, lab), 0)} | {a.get((split, lab), 0)} |\n")

    L.append("\n## 정상(0) 출처별 잔존: 전 → 후 (하드 네거티브 보존 확인)\n\n")
    L.append("| 출처 | 전 | 후 |\n|---|---|---|\n")
    for s in sorted(before_norm_src, key=lambda x: before_norm_src[x], reverse=True):
        L.append(f"| {s} | {before_norm_src[s]} | {after_norm_src.get(s, 0)} |\n")

    # balance 후 길이 지름길 실측 (train 기준 — 모델이 학습하는 분포)
    tr_after = [r for r in after if r["split"] == "train"]
    best, chance, rule = length_shortcut_accuracy(tr_after)
    ta = [len(r["text"]) for r in tr_after if int(r["label"]) == 1]
    tn = [len(r["text"]) for r in tr_after if int(r["label"]) == 0]
    L.append("\n## balance 후 길이 지름길 실측 (train, 비율 독립 지표)\n\n")
    L.append(f"- 공격 길이 중앙값 {int(st.median(ta)) if ta else 0} / 정상 중앙값 {int(st.median(tn)) if tn else 0}\n")
    L.append(f"- 길이 단일 임계값 최대 balanced accuracy: **{best*100:.1f}%** "
             f"(우연 50%, 규칙: {rule})\n")
    gap = (best - 0.5) * 100
    verdict = ("길이 정보 사실상 없음 ✅" if gap < 7 else
               f"길이가 우연 대비 {gap:.1f}%p 정보 제공 🟠 — 일지에 한계로 명시 "
               "(성능 일부가 길이에서 올 수 있음)")
    L.append(f"- 판정: {verdict}\n")

    n_pos = sum(1 for r in after if int(r["label"]) == 1)
    n_neg = len(after) - n_pos
    L.append("\n## 최종\n")
    L.append(f"- 총 {len(after)}개 (정상 {n_neg} / 공격 {n_pos})\n")
    L.append("- 증강 미실시 — is_augmented 전부 False. 적대적 증강은 이후 train-only 단계.\n")

    REPORT.write_text("".join(L), encoding="utf-8")


def selftest():
    rng = random.Random(0)
    # 2:1 다운샘플 확인: 공격 2 + 정상 10(두 출처) → 정상 4 남아야
    rows = ([{"id": f"a{i}", "text": "x"*10, "label": 1, "source": "s", "split": "train"} for i in range(2)]
            + [{"id": f"n{i}", "text": "y"*10, "label": 0, "source": "A", "split": "train"} for i in range(6)]
            + [{"id": f"m{i}", "text": "z"*10, "label": 0, "source": "B", "split": "train"} for i in range(4)])
    out = balance_split(rows, rng, True, 2)
    na = sum(1 for r in out if r["label"] == 1); nn = sum(1 for r in out if r["label"] == 0)
    assert na == 2 and nn == 4, (na, nn)
    # 출처 비례 확인: A:B = 6:4 → 4개 중 대략 A2~3, B1~2
    src = Counter(r["source"] for r in out if r["label"] == 0)
    assert src["A"] + src["B"] == 4 and src["A"] >= src["B"], src
    # 정상이 목표보다 적으면 다 씀
    out2 = balance_split(rows[:2] + rows[2:5], rng, True, 2)   # 공격2 목표정상4, 실제정상3
    assert sum(1 for r in out2 if r["label"] == 0) == 3
    # 길이 지름길: 공격이 전부 길고 정상이 전부 짧으면 balanced acc 100%
    perfect = ([{"text": "x"*100, "label": 1} for _ in range(5)]
               + [{"text": "y"*10, "label": 0} for _ in range(5)])
    best, chance, _ = length_shortcut_accuracy(perfect)
    assert abs(best - 1.0) < 1e-9 and chance == 0.5, (best, chance)
    # 길이가 라벨과 무관하면 best 는 0.5 근처(>=0.5)
    import random as _r; _r.seed(1)
    noise = [{"text": "x"*_r.randint(10, 100), "label": _r.randint(0, 1)} for _ in range(200)]
    b2, c2, _ = length_shortcut_accuracy(noise)
    assert b2 >= 0.5 and c2 == 0.5, (b2, c2)
    print("[selftest] 통과: balance_split(2:1, 출처비례, 부족시전량) / length_shortcut_accuracy")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()