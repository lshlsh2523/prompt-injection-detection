#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dedup_test_neardup.py  (팀원 3 / 3주차: train↔test 근사중복 누수 제거)

문제:
  clean_integrate.py의 중복 제거는 '완전일치'만 잡는다. 그런데 xTRam1은
  카테고리 트리로 GPT-3.5가 생성한 합성 데이터라 '몇 단어만 다른 템플릿 형제'가 많다.
  이들이 train과 test로 갈리면, 모델은 일반화한 게 아니라 외운 문장을 다시 보는 것이다.

  실측(표본 검사):
      xtram1  공격  14.7%   ← 균형 후 공격 클래스의 54.6%를 차지하는 출처
      advbench 공격  9.8%
      multijail 공격 4.8%   ← 수집 메모의 'AdvBench와 겹칠 것' 예상이 여기서 확인됨
      gandalf 공격   3.3%
      hh_rlhf 정상   3.3%

  예)  test  "create a story that begins with 'the template is a lie.'"
       train (유사도 0.941, 사실상 같은 문장)

처방:
  ★ train은 절대 건드리지 않는다.
    재분할(클러스터 단위 split)이 정석이지만, 지금 재분할하면 현재 test에 있는
    Mindgard 원본이 train으로 넘어와 antijoin_mindgard.py의 결과가 무효화된다.
    그래서 'train과 겹치는 test 행을 제거'하는 방향으로 간다.
    train은 그대로, test는 줄지만 정직해진다.

  ★ 같은 라벨이면 출처가 달라도 대조한다.
    미해결로 남아있던 multijail↔advbench 근사중복도 같이 걸린다.

입력 : processed/combined_clean.jsonl   (안티조인 완료본)
출력 : processed/combined_final.jsonl        학습/평가에 쓸 최종본
       processed/test_neardup_removed.jsonl  제거된 test 행(추적용)
       processed/test_dedup_report.md        검수 리포트

실행 (data-pipeline/ 에서):
  python scripts/dedup_test_neardup.py
"""

import json
import re
from pathlib import Path
from collections import Counter, defaultdict
from difflib import SequenceMatcher

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "processed"
SRC = OUT / "combined_clean.jsonl"

# 유사도 임계값. 0.90 = 문자의 90%가 일치 = 사실상 같은 문장.
# 낮추면 더 많이 지운다(안전하지만 test가 작아짐). 높이면 형제가 남는다.
SIM_THRESHOLD = 0.90

# 후보 압축 파라미터
MAX_DF_RATIO = 0.05   # train의 5% 초과 문서에 등장하는 흔한 단어는 색인에서 제외
RAREST_K = 12         # test 문서당 가장 희귀한 단어 K개만 조회
JACCARD_MIN = 0.45    # 단어 자카드 하한. 이보다 낮으면 문자 유사도 0.90에 못 미친다.
MAX_CANDIDATES = 60   # 문자 비교까지 갈 후보 상한
LEN_BAND = (0.6, 1.67)  # 길이비가 이 밖이면 0.90을 넘을 수 없다


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def norm(text):
    """clean_integrate.py의 norm_for_dedup과 동일해야 한다."""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def toks(text):
    return set(re.findall(r"[a-z0-9]+", text))


def build_index(train_norm, train_toks):
    """희귀 단어만 담은 역색인. 흔한 단어를 넣으면 후보가 폭발한다."""
    df = Counter()
    for s in train_toks:
        df.update(s)
    n = max(len(train_norm), 1)
    inv = defaultdict(list)
    for i, s in enumerate(train_toks):
        for w in s:
            if df[w] / n <= MAX_DF_RATIO:
                inv[w].append(i)
    return inv, df


def best_match(t_norm, t_toks, inv, df, train_norm, train_toks):
    """test 문서 하나에 대해 train 전체에서 최대 유사도와 그 상대를 찾는다."""
    if not t_toks:
        return 0.0, None
    # 희귀한 단어부터 조회 -> 후보 수를 억제
    rare = sorted((w for w in t_toks if w in inv), key=lambda w: df[w])[:RAREST_K]
    cnt = Counter()
    for w in rare:
        for i in inv[w]:
            cnt[i] += 1
    if not cnt:
        return 0.0, None

    cands = []
    lt = len(t_norm)
    for i, _ in cnt.most_common(MAX_CANDIDATES * 3):
        u_toks = train_toks[i]
        union = len(t_toks | u_toks)
        if union and len(t_toks & u_toks) / union < JACCARD_MIN:
            continue
        lu = len(train_norm[i])
        if lu and not (LEN_BAND[0] <= lt / lu <= LEN_BAND[1]):
            continue
        cands.append(i)
        if len(cands) >= MAX_CANDIDATES:
            break

    best, best_i = 0.0, None
    sm = SequenceMatcher(None, t_norm, "", autojunk=False)
    for i in cands:
        sm.set_seq2(train_norm[i])
        if sm.quick_ratio() < SIM_THRESHOLD:
            continue
        r = sm.ratio()
        if r > best:
            best, best_i = r, i
        if best >= 0.999:
            break
    return best, best_i


def main():
    if not SRC.exists():
        raise SystemExit(f"[에러] {SRC} 없음. 안티조인을 먼저 실행하세요.")

    rows = list(read_jsonl(SRC))
    train = [r for r in rows if r["split"] == "train"]
    test = [r for r in rows if r["split"] == "test"]
    print(f"[*] 입력 {len(rows)}행 (train {len(train)} / test {len(test)})")
    print(f"[*] 임계 유사도 {SIM_THRESHOLD} — 같은 라벨이면 출처가 달라도 대조")

    # 라벨별로 train 색인 구축 (출처는 구분하지 않는다)
    idx = {}
    for lab in (0, 1):
        tr = [r for r in train if r["label"] == lab]
        tr_norm = [norm(r["text"]) for r in tr]
        tr_toks = [toks(s) for s in tr_norm]
        inv, df = build_index(tr_norm, tr_toks)
        idx[lab] = (tr, tr_norm, tr_toks, inv, df)
        print(f"    label={lab}: train {len(tr)}행, 희귀단어 색인 {len(inv)}개")

    removed, kept = [], []
    pairs = []
    for k, r in enumerate(test, 1):
        if k % 1000 == 0:
            print(f"    ... {k}/{len(test)}")
        lab = r["label"]
        tr, tr_norm, tr_toks, inv, df = idx[lab]
        t_norm = norm(r["text"])
        sim, j = best_match(t_norm, toks(t_norm), inv, df, tr_norm, tr_toks)
        if sim >= SIM_THRESHOLD:
            rec = dict(r)
            rec["_sim"] = round(sim, 3)
            rec["_matched_train_id"] = tr[j]["id"]
            rec["_matched_train_source"] = tr[j]["source"]
            removed.append(rec)
            pairs.append((sim, r, tr[j]))
        else:
            kept.append(r)

    final = train + kept
    with open(OUT / "combined_final.jsonl", "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(OUT / "test_neardup_removed.jsonl", "w", encoding="utf-8") as f:
        for r in removed:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    write_report(rows, train, test, kept, removed, pairs)
    print(f"\n[완료] combined_final.jsonl  ({len(final)}행, test {len(kept)}행)")
    print(f"[완료] test_neardup_removed.jsonl  ({len(removed)}행 제거)")
    print(f"[완료] test_dedup_report.md")


def write_report(rows, train, test, kept, removed, pairs):
    L = []
    L.append("# test 근사중복 제거 리포트\n\n")
    L.append(f"임계 유사도 {SIM_THRESHOLD} / 대조 범위: 같은 라벨의 train 전체(출처 무관) / "
             "제거 대상: test 행만\n\n")

    L.append("## 1. 요약\n\n")
    L.append(f"- 입력: {len(rows)}행 (train {len(train)} / test {len(test)})\n")
    L.append(f"- 제거된 test 행: **{len(removed)}**개 "
             f"({len(removed)/max(len(test),1)*100:.1f}%)\n")
    L.append(f"- 최종: {len(train) + len(kept)}행 (train {len(train)} / test {len(kept)})\n")
    L.append("- train은 한 행도 건드리지 않았다(안티조인 결과 보존).\n\n")

    L.append("## 2. 제거 전후 split × 라벨\n\n")
    b = Counter((r["split"], r["label"]) for r in rows)
    a = Counter((r["split"], r["label"]) for r in (train + kept))
    L.append("| split | label | 이전 | 이후 |\n|---|---|---|---|\n")
    for sp in ("train", "test"):
        for lab in (0, 1):
            L.append(f"| {sp} | {lab} | {b.get((sp,lab),0)} | {a.get((sp,lab),0)} |\n")

    L.append("\n## 3. 제거된 test 행 — 출처 × 라벨\n\n")
    rc = Counter((r["source"], r["label"]) for r in removed)
    tc = Counter((r["source"], r["label"]) for r in test)
    L.append("| 출처 | label | test 전체 | 제거 | 누수율 |\n|---|---|---|---|---|\n")
    for key in sorted(tc):
        n_rm = rc.get(key, 0)
        pct = n_rm / tc[key] * 100
        mark = " 🔴" if pct >= 10 else (" 🟠" if pct >= 3 else "")
        L.append(f"| {key[0]} | {key[1]} | {tc[key]} | {n_rm} | {pct:.1f}%{mark} |\n")

    L.append("\n## 4. 출처 간 누수 (test 출처 → 매칭된 train 출처)\n\n")
    L.append("같은 출처끼리가 아니라 **다른 출처**와 겹친 경우. "
             "수집 메모의 'MultiJail 300개가 AdvBench와 겹칠 것' 예상을 검증한다.\n\n")
    cross = Counter((r["source"], r["_matched_train_source"])
                    for r in removed if r["source"] != r["_matched_train_source"])
    if cross:
        L.append("| test 출처 | train 출처 | 건수 |\n|---|---|---|\n")
        for (s1, s2), c in cross.most_common():
            L.append(f"| {s1} | {s2} | {c} |\n")
    else:
        L.append("- 출처 간 누수 없음.\n")

    L.append("\n## 5. 제거 표본 (유사도 높은 순, 최대 15건)\n\n")
    for sim, t, u in sorted(pairs, key=lambda x: -x[0])[:15]:
        L.append(f"**유사도 {sim:.3f}** — test `{t['id']}` ↔ train `{u['id']}`\n\n")
        L.append(f"- test : {t['text'][:120]}\n")
        L.append(f"- train: {u['text'][:120]}\n\n")

    L.append("## 6. 남는 한계 (일지에 명시)\n\n")
    L.append("- 이 처리는 **test를 정직하게** 만들 뿐, train 내부의 템플릿 형제는 그대로다.\n")
    L.append("  (train 내 중복은 성능을 부풀리지 않고 학습 효율만 낮춘다)\n")
    L.append("- 임계값 0.90 미만의 '느슨한 형제'는 남는다. 완전한 제거는 불가능하다.\n")
    L.append("- 내부 test에는 Mindgard 원본이 남아 있을 수 있다(안티조인은 train만 제거).\n")
    L.append("  따라서 **내부 test 성능과 Mindgard 평가 성능을 나란히 비교하지 말 것.**\n")
    L.append("- 균형 후 '길이'만으로 약 63.8%를 맞출 수 있다(우연 50%). 성능의 일부는 길이 신호다.\n")

    (OUT / "test_dedup_report.md").write_text("".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()