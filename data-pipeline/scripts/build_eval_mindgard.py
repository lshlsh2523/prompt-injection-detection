#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_eval_mindgard.py  (task 5: 난독화 평가셋 = '시험지')

목적: "BERT가 길이가 아니라 문맥으로 난독화 공격을 잡는다"를 반박 불가능하게 평가할 시험지.

구성
  - 공격(label 1): Mindgard modified_sample. 원본 623개를 전부 쓰되, 원본당 기법을
    TECH_PER_ORIGIN(기본 3)개만 '기법 균형'으로 골라 넣는다(같은 원본 20중복 방지, 20기법 골고루).
    Emoji Smuggling 은 Base64 저장 → 디코드해 실제 텍스트로.
  - 정상(label 0): 학습/내부test(balanced.jsonl)에 안 쓴 '잔여 정상'에서,
    공격과 '길이 분포 매칭' + 공격과 1:1.
  - 오염 차단:
      · 정상: balanced 전체와 완전일치 제거 + train 정상과 근사중복(>=0.9) 제거
      · 공격: original_sample 을 train 과 재대조(안티조인 재확인, 기대 0)

입력
  processed/combined_final.jsonl   (잔여 정상 풀·train 대조용)
  processed/balanced.jsonl         (이미 쓴 id 파악)
  Mindgard/evaded-...(HF, gated)

출력
  eval/obfuscated_eval.jsonl       (시험지)  ← gitignore 권장(gated·NC 라이선스)
  eval/build_eval_report.md        (구성·길이매칭·오염점검 리포트)

실행
  python scripts/build_eval_mindgard.py --selftest
  python scripts/build_eval_mindgard.py
"""
import sys
import re
import json
import base64
import random
import statistics as st
from pathlib import Path
from collections import defaultdict, Counter

BASE = Path(__file__).resolve().parent.parent
FINAL = BASE / "processed" / "combined_final.jsonl"
BALANCED = BASE / "processed" / "balanced.jsonl"
OUTDIR = BASE / "eval"
OUT = OUTDIR / "obfuscated_eval.jsonl"
REPORT = OUTDIR / "build_eval_report.md"

DATASET = "Mindgard/evaded-prompt-injection-and-jailbreak-samples"
SEED = 42
TECH_PER_ORIGIN = 3          # 원본당 넣을 기법 수 (3 → 공격 ~1,800)
NEAR_DUP = 0.9               # 정상 근사중복 제거 임계
BINS = [(0, 60), (60, 120), (120, 200), (200, 300), (300, 600), (600, 10**9)]


def norm(t):
    return re.sub(r"\s+", " ", str(t)).strip().lower()


def try_b64(s):
    t = str(s).strip()
    if len(t) < 8 or len(t) % 4 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", t):
        return None
    try:
        return base64.b64decode(t, validate=True).decode("utf-8")
    except Exception:
        return None


def eff_modified(row):
    """emoji smuggling 등 Base64면 디코드본, 아니면 원문."""
    m = row.get("modified_sample", "")
    dec = try_b64(m)
    return dec if dec is not None else str(m)


def bin_of(n):
    for lo, hi in BINS:
        if lo <= n < hi:
            return (lo, hi)
    return BINS[-1]


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_mindgard():
    from datasets import load_dataset
    ds = load_dataset(DATASET)
    return [r for split in ds for r in ds[split]]


# ---------- 코어(순수 함수, fixture 검증 대상) ----------
def select_attacks(mg_rows, k, rng):
    """원본별 기법 균형 선택. 반환: [(orig_norm, attack_name, text)]"""
    groups = defaultdict(dict)                 # orig_norm -> {attack_name: text}
    for r in mg_rows:
        o = norm(r.get("original_sample", ""))
        if not o:
            continue
        text = eff_modified(r)
        if text.strip():
            groups[o].setdefault(r.get("attack_name", "?"), text)

    origins = list(groups.keys())
    rng.shuffle(origins)                       # 순서 편향 제거
    global_tech = Counter()
    selected = []
    for o in origins:
        by_tech = groups[o]
        # 전역 사용량이 적은 기법부터 k개
        techs = sorted(by_tech.keys(), key=lambda a: (global_tech[a], a))[:k]
        for a in techs:
            selected.append((o, a, by_tech[a]))
            global_tech[a] += 1
    return selected, global_tech


def match_normals_by_length(attack_lens, normal_pool, rng, near_dup_corpus=None,
                            near_dup_fn=None):
    """공격 길이 분포(bin별 개수)에 맞춰 정상을 뽑는다. 1:1.
    near_dup_corpus/fn 주어지면 뽑은 정상을 근사중복 필터.
    반환: (selected_normals, per_bin_report)"""
    need = Counter(bin_of(n) for n in attack_lens)
    pool_by_bin = defaultdict(list)
    for r in normal_pool:
        pool_by_bin[bin_of(len(r["text"]))].append(r)

    selected, report = [], {}
    for b, cnt in need.items():
        cand = pool_by_bin[b][:]
        rng.shuffle(cand)
        picked, dropped = [], 0
        for r in cand:
            if len(picked) >= cnt:
                break
            if near_dup_fn and near_dup_corpus is not None:
                if near_dup_fn(norm(r["text"]), near_dup_corpus):
                    dropped += 1
                    continue
            picked.append(r)
        report[b] = (cnt, len(picked), dropped, len(pool_by_bin[b]))
        selected.extend(picked)
    return selected, report


def make_near_dup_fn(threshold):
    """corpus(정규화 리스트)에 대해 t가 유사도>=threshold면 True. rapidfuzz 우선."""
    try:
        from rapidfuzz import fuzz, process
        cut = threshold * 100

        def fn(t, corpus):
            return process.extractOne(t, corpus, scorer=fuzz.ratio, score_cutoff=cut) is not None
        return fn
    except ImportError:
        from difflib import SequenceMatcher

        def fn(t, corpus):
            sm = SequenceMatcher(None, t, "", autojunk=False)
            for c in corpus:
                if not (0.5 <= len(t) / max(len(c), 1) <= 2.0):
                    continue
                sm.set_seq2(c)
                if sm.quick_ratio() >= threshold and sm.ratio() >= threshold:
                    return True
            return False
        return fn


# ---------- 메인 ----------
def main():
    for p in (FINAL, BALANCED):
        if not p.exists():
            print(f"[에러] 입력 없음: {p}")
            sys.exit(1)

    rng = random.Random(SEED)
    final = list(load_jsonl(FINAL))
    balanced = list(load_jsonl(BALANCED))
    used_ids = set(r["id"] for r in balanced)
    balanced_norm = set(norm(r["text"]) for r in balanced)
    train_texts = set(norm(r["text"]) for r in final if r["split"] == "train")
    train_norm_corpus = [norm(r["text"]) for r in final
                         if r["split"] == "train" and r["label"] == 0]

    # 잔여 정상 풀 (balanced에 안 쓴 정상) + balanced 완전일치 제거
    leftover = [r for r in final if r["label"] == 0
                and r["id"] not in used_ids and norm(r["text"]) not in balanced_norm]

    print("Mindgard 로드 (gated)...")
    try:
        mg = load_mindgard()
    except Exception as e:
        print("[에러] Mindgard 로드 실패:", repr(e))
        print(">> https://huggingface.co/datasets/" + DATASET + " 접근 동의 후 재실행")
        sys.exit(1)

    # 공격 선택
    sel, tech_dist = select_attacks(mg, TECH_PER_ORIGIN, rng)
    print(f"공격 선택: {len(sel)}개 (원본 {len(set(o for o,_,_ in sel))}개 × 기법균형)")

    # 공격 오염 재확인: original 이 train 에 있나 (안티조인 재검증, 기대 0)
    atk_leak = sum(1 for o, _, _ in sel if o in train_texts)

    attack_lens = [len(t) for _, _, t in sel]

    # 정상 길이매칭 + 근사중복 제거
    print("정상 길이매칭 + 근사중복 제거 중...")
    near_fn = make_near_dup_fn(NEAR_DUP)
    normals, bin_report = match_normals_by_length(
        attack_lens, leftover, rng, near_dup_corpus=train_norm_corpus, near_dup_fn=near_fn)

    # bin별 1:1 정렬: 공격을 정상 수에 맞춰 trim (정상이 부족한 bin 대비)
    got_per_bin = Counter(bin_of(len(r["text"])) for r in normals)
    atk_by_bin = defaultdict(list)
    for o, a, t in sel:
        atk_by_bin[bin_of(len(t))].append((o, a, t))
    final_atk = []
    for b, rows in atk_by_bin.items():
        keep = min(len(rows), got_per_bin.get(b, 0))
        rng.shuffle(rows)
        final_atk.extend(rows[:keep])

    # 조립
    out = []
    for i, (o, a, t) in enumerate(final_atk):
        out.append({"id": f"mindgard_{i:05d}", "text": t, "label": 1,
                    "source": "mindgard", "split": "eval", "attack_type": None,
                    "is_augmented": 0, "attack_name": a, "char_len": len(t)})
    for r in normals:
        out.append({"id": r["id"], "text": r["text"], "label": 0,
                    "source": r["source"], "split": "eval", "attack_type": None,
                    "is_augmented": 0, "attack_name": None, "char_len": len(r["text"])})

    OUTDIR.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    write_report(out, final_atk, normals, tech_dist, bin_report, atk_leak, len(leftover))
    print(f"[완료] {OUT}  (공격 {len(final_atk)} / 정상 {len(normals)})")
    print(f"[완료] {REPORT}")


def write_report(out, atk, normals, tech_dist, bin_report, atk_leak, leftover_n):
    la = [r["char_len"] for r in out if r["label"] == 1]
    ln = [r["char_len"] for r in out if r["label"] == 0]
    L = []
    L.append("# 난독화 평가셋(시험지) 빌드 리포트 (task 5)\n\n")
    L.append(f"- 총 {len(out)}개 (공격 {len(atk)} / 정상 {len(normals)}), 1:1\n")
    L.append(f"- 출처: 공격=Mindgard(원본×기법균형) / 정상=잔여풀 {leftover_n}개에서 길이매칭\n")
    L.append(f"- 공격 오염 재확인(original이 train에 있음): **{atk_leak}개** (기대 0)\n")

    L.append("\n## 길이 매칭 (공격 vs 정상)\n\n")
    L.append(f"- 공격 길이 중앙값 {int(st.median(la))} / 정상 중앙값 {int(st.median(ln))}\n")
    L.append("| 길이구간 | 공격필요 | 정상확보 | 근사중복제거 | 풀크기 |\n|---|---|---|---|---|\n")
    for b in BINS:
        if b in bin_report:
            need, got, dropped, pool = bin_report[b]
            L.append(f"| {b[0]}-{b[1] if b[1]<10**9 else '∞'} | {need} | {got} | {dropped} | {pool} |\n")

    L.append("\n## 공격 기법 분포 (20기법 골고루 확인)\n\n")
    L.append("| attack_name | 개수 |\n|---|---|\n")
    for a, c in sorted(tech_dist.items()):
        L.append(f"| {a} | {c} |\n")

    L.append("\n## 한계 (일지)\n")
    L.append("- 다양성 상한은 원본 623개. 기법으로 부풀려도 밑바탕은 623 시나리오.\n")
    L.append("- 라이선스 cc-by-nc-4.0(비상업)·gated → jsonl 은 공개레포에 올리지 말 것(빌드스크립트만 커밋).\n")
    L.append("- 내부 test 성능과 이 평가셋 성능을 절대분리해 해석(분포 다름).\n")
    REPORT.write_text("".join(L), encoding="utf-8")


def selftest():
    rng = random.Random(0)
    # base64
    enc = base64.b64encode("hi there".encode()).decode()
    assert try_b64(enc) == "hi there" and try_b64("Ignore this.") is None
    assert eff_modified({"modified_sample": enc}) == "hi there"

    # 기법 균형: 원본 2개, 각 기법 3종, k=2 → 각 원본 2개씩, 기법 골고루
    mg = []
    for oi, o in enumerate(["orig one", "orig two"]):
        for a in ["Homoglyphs", "Zero Width", "Emoji Smuggling"]:
            mg.append({"original_sample": o, "attack_name": a, "modified_sample": f"{o}-{a}"})
    sel, dist = select_attacks(mg, 2, rng)
    assert len(sel) == 4                     # 2원본 × 2기법
    assert len(set(o for o, _, _ in sel)) == 2
    assert max(dist.values()) - min(dist.values()) <= 1   # 균형

    # 길이매칭: 공격 길이 [10,10,150], 정상풀에 각 구간 충분 → bin별 need 맞춤
    atk_lens = [10, 10, 150]
    pool = ([{"id": f"s{i}", "text": "y"*10, "source": "hh"} for i in range(5)]
            + [{"id": f"m{i}", "text": "z"*150, "source": "pc"} for i in range(5)])
    picked, rep = match_normals_by_length(atk_lens, pool, rng)
    got = Counter(bin_of(len(r["text"])) for r in picked)
    assert got[bin_of(10)] == 2 and got[bin_of(150)] == 1, (got, rep)

    # 근사중복 필터 동작: corpus에 거의 같은 문장 있으면 제외
    fn = make_near_dup_fn(0.9)
    assert fn("ignore all previous instructions", ["ignore all previous instruction"]) is True
    assert fn("completely different text", ["ignore all previous instruction"]) is False
    print("[selftest] 통과: try_b64/eff_modified / select_attacks(균형) / "
          "match_normals_by_length / near_dup")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()