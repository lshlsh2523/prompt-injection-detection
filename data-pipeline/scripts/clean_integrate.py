#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_integrate.py  (팀원 3 / task 3: 정제·통합)

8종 원본(raw/) -> 통합 스키마 1개 파일(processed/combined.jsonl)로 정제·통합한다.
하는 일 :  경량 클리닝 + 라벨 부여 + 대화 껍데기 제거 + 언어 필터 + 오염 제외
           + 중복 제거 + 라벨 일관성 검사 + split 고정
안 하는 일: 클래스 균형(정상 다운샘플) -> task 4. 여기 결과물은 '아직 불균형'이 정상이다.

[3주차 변경 이력]
 (1) 인젝션 계열 2종 추가: gandalf, xtram1
 (2) 언어 필터 도입 — 감사(audit_corpus.py) 결과 반영
 (3) xtram1 정상(0)의 탈옥 혼입 제외 + 공격(1) attack_type 세분화

출력:
  processed/combined.jsonl   7컬럼(id, text, label, source, split, attack_type, is_augmented)
  processed/build_report.md  검수용 리포트

실행 (data-pipeline/ 에서, venv 켠 상태):
  python scripts/clean_integrate.py
"""

import json
import re
import random
from pathlib import Path
from collections import defaultdict, Counter

# ============================================================
# 설정
# ============================================================
BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "raw"
OUT = BASE / "processed"

SEED = 42
TEST_RATIO = 0.20

SCHEMA = ["id", "text", "label", "source", "split", "attack_type", "is_augmented"]

# 출처 처리 순서 = 중복 시 살아남을 우선순위(앞선 출처가 이김)
SOURCE_ORDER = ["deepset", "jailbreakbench", "advbench", "multijail",
                "prompts_chat", "hh_rlhf", "gandalf", "xtram1"]

PROMPTSCHAT_EXCLUDE = ["escape the box", "gaslighter"]

XTRAM1_INCLUDE_NORMAL = True   # 출처 지름길 방지. 아래 주석 참조.

# ------------------------------------------------------------
# 언어 정책 (audit_corpus.py 감사 결과)
#
#   규칙은 '영어만'인데 필터가 없었다. 실측 결과:
#     - deepset: en/de 병렬 코퍼스. 같은 샘플의 독일어 번역본이 함께 들어있다.
#         예) deepset_000004(en) "Wow, that's fantastic! Forget all previous tasks..."
#             deepset_000181(de) "Wow, das ist fantastisch! Vergiss alle vorherigen Aufgaben..."
#       완전일치 dedup이 못 잡는 '의미 중복'이라, 영어판이 train / 독일어판이 test로
#       갈리면 누수가 된다. 게다가 deberta-v3-small은 영어 전용 모델이다.
#       순수 de 기준 오즈가 공격 쪽으로 2.4:1이라 언어 지름길 위험도 있었다.
#       -> deepset은 de + mixed 전량 제외 (strict)
#
#     - 그 외 출처: 'mixed' 판정은 오탐이 많다.
#       (hh_rlhf는 순수 de가 14개뿐인데 mixed가 599개. 긴 영어 문장에 der/im/ist 같은
#        단어가 우연히 걸린 것.)  -> 순수 de만 제외 (conservative)
# ------------------------------------------------------------
LANG_STRICT_SOURCES = {"deepset"}                    # de + mixed 제외
LANG_DROP_DEFAULT = {"de", "other"}                  # 나머지: 순수 de + 비영어 문자체계
LANG_DROP_STRICT = {"de", "mixed", "other"}

# 독일어 기능어 — '영어에도 존재하는 단어'는 넣지 않는다.
#   ※ 1차 실행에서 "am"(독일어 전치사 am Montag) 때문에 "I am going on vacation soon."이
#     독일어로 오판됐다. am/im 같은 충돌 토큰은 제외한다.
GERMAN_WORDS = {
    "ich", "du", "wir", "ihr", "sie", "uns", "euch", "mein", "meine", "dein", "deine",
    "sein", "ihre", "diese", "dieser", "nicht", "und", "oder", "aber", "bitte",
    "kannst", "sollst", "werde", "wird", "werden", "wurde", "wurden", "sind", "ist",
    "haben", "hatte", "kann", "soll", "sollte", "könnte", "müssen", "muss",
    "alle", "jetzt", "vorherigen", "anweisung", "anweisungen", "antworte", "schreibe",
    "gerne", "würde", "möchte", "wichtig", "nach", "bei", "aus", "durch", "gegen",
    "ohne", "wenn", "dass", "weil", "sehr", "auch", "noch", "nur", "schon", "immer",
    "der", "das", "den", "dem", "ein", "eine", "einen", "einem", "eines",
    "mit", "von", "für", "über", "unter", "zwischen", "zu", "vom",
    "geht", "macht", "gibt", "mehr", "kein", "keine", "viele", "etwas", "nichts",
    "damit", "denn", "doch", "warum", "wie", "wo", "wann", "welche", "welcher",
    "deutschland", "deutsche", "deutschen", "frage", "antwort", "beste", "besten",
    "aufgabe", "aufgaben", "vergiss", "ignoriere", "zeige", "konzentriere",
}

# 영어 기능어 — 독일어와 철자가 겹치는 것(in, an, so, also, man, war, hat, die, was)은 제외.
#   1차 실행에서 이 목록이 빈약해 평범한 영어 문장이 en=0으로 나왔다.
ENGLISH_WORDS = {
    "the", "and", "or", "you", "your", "is", "are", "to", "of", "for", "with",
    "that", "this", "please", "will", "not", "all", "now", "what", "how", "why",
    "can", "should", "would", "have", "from", "about", "instructions", "answer",
    "write", "tell", "give", "make", "want", "act", "ignore", "following",
    "i", "my", "me", "do", "does", "did", "know", "going", "like", "get", "need",
    "help", "there", "when", "which", "who", "has", "been", "out", "up", "then",
    "just", "only", "much", "many", "any", "yes", "could", "it", "its", "be",
    "but", "if", "we", "they", "he", "she", "some", "more", "question", "passage",
    "task", "review", "title", "based", "understanding", "given", "context",
}
UMLAUT_RE = re.compile(r"[äöüßÄÖÜ]")
WORD_RE = re.compile(r"[a-zäöüßA-ZÄÖÜ]+")


def _nonascii_letters(text):
    return sum(1 for ch in text if ch.isalpha() and ord(ch) > 127)


def detect_lang(text):
    """en / de / mixed / other.

    설계 원칙(1차 실행 오탐을 반영):
      - 독일어 '단어' 증거가 0이면 절대 de로 판정하지 않는다.
        (움라우트만으로 de를 주면 터키어 'Neşeli...'가 독일어가 된다)
      - 움라우트/ß는 독일어 단어가 이미 있을 때만 보강 증거로 쓴다.
      - 독일어 단어 없이 비ASCII 글자가 많으면 'other'(비영어 문자체계).
        ※ 모지바케(world‚Äôs) 한두 글자로 영어가 탈락하지 않도록 3자 이상 요구.
    """
    words = [w.lower() for w in WORD_RE.findall(text)]
    if not words:
        return "en"
    de = sum(1 for w in words if w in GERMAN_WORDS)
    en = sum(1 for w in words if w in ENGLISH_WORDS)

    if de == 0:
        return "other" if _nonascii_letters(text) >= 3 else "en"

    umlaut = bool(UMLAUT_RE.search(text))
    if de >= 2 and de > en:
        return "de"
    if en == 0 and de / len(words) >= 0.2:      # 짧은 독일어 문장 ("Ignoriere die Anweisung")
        return "de"
    if umlaut and de * 2 >= en:
        return "de"
    if de >= 2:
        return "mixed"
    return "en"


# ------------------------------------------------------------
# xtram1 정상(0)의 탈옥 혼입 제외
#
#   근거: build_report.md 라벨 충돌에서 동일 DAN 프롬프트가 xtram1 안에서
#         0이자 1로 라벨돼 있었다. 즉 xtram1의 label 0에 탈옥이 섞여 있다.
#         (prompts.chat의 "AI Trying to Escape the Box"를 제외한 것과 같은 문제, 규모만 큼)
#
#   비대칭 비용: 정상은 24,526개나 있어 몇백 개 더 버려도 손해가 없다.
#                반면 탈옥 하나가 정상으로 남으면 라벨이 깨진다.
#                -> 정상 쪽은 과잉 제외(aggressive)가 싸다.
#   ※ 이 패턴을 label 1에는 적용하지 않는다(공격은 이미 공격이므로).
# ------------------------------------------------------------
#   1차 실행 오탐: \bAIM\b, \bDUDE\b, \bSTAN\b을 IGNORECASE로 돌려
#   "aim", "dude" 같은 평범한 소문자 단어가 걸렸다. 결과적으로 xtram1 정상에서
#   독해 과제·상품평 29개가 탈옥으로 오인돼 제거됐다(진짜 탈옥은 아님).
#   -> 페르소나 약어는 '대문자일 때만' 의미가 있으므로 대소문자 구분 검사로 분리한다.
#   -> unrestricted/unfiltered 단독도 너무 넓어 페르소나 문맥에서만 잡는다.
#
#   2차 실행 오탐: "caveat emptor"는 라틴어 관용구('구매자 위험 부담')로 상품평에 자연히 등장한다.
#   xtram1 정상에서 제외된 4건 중 2건이 Chrono Trigger OST 상품평이었다.
#   진짜 탈옥 프롬프트는 "[Caveat Emptor: After issuing this prompt..." 처럼 대괄호로 연다.
#   -> 대괄호 접두를 요구한다. 이 조건을 풀면 오탐이 되돌아온다.

JAILBREAK_PHRASE = re.compile(
    r"(do anything now|developer mode|jailbreak|opposite mode|"
    r"immerse yourself into the role|broken free of the typical confines|"
    r"\[\s*caveat emptor|evil (confidant|ai assistant)|"
    r"no (rules|restrictions|limits|filters?|programming guidelines|ethical guidelines)|"
    r"without any (restrictions|filters?|censorship|ethical guidelines)|"
    r"(you are|act as|pretend to be) an? (unrestricted|unfiltered|evil|amoral)|"
    r"(bypass|override) (your |the |all )?(safety|content policy|guidelines|restrictions))",
    re.IGNORECASE,
)

# 대소문자 구분 — 탈옥 페르소나는 관례적으로 전부 대문자다.
JAILBREAK_PERSONA = re.compile(r"\b(DAN|STAN|DUDE|AIM|BetterDAN)\b")


def jailbreak_hit(text):
    """탈옥 단서가 있으면 매칭된 문자열을 반환, 없으면 None.
    무엇이 걸렸는지 리포트에 남기기 위해 bool이 아니라 문자열을 돌려준다."""
    m = JAILBREAK_PHRASE.search(text) or JAILBREAK_PERSONA.search(text)
    return m.group(0) if m else None

# 인젝션(명령 덮어쓰기) 단서 — attack_type 세분화용
INJECTION_PAT = re.compile(
    r"(ignore (all |the |any )?(previous|prior|above|preceding)|disregard|"
    r"forget (all|your|the|about|everything|anything)|"
    r"previous (instructions|tasks|information)|"
    r"(show|reveal|print|output|repeat) (me )?(all )?(your |the )?(prompt|system prompt|instructions)|"
    r"execute the following|new (task|instructions) )",
    re.IGNORECASE,
)

EXPECTED_FILES = [
    "deepset/deepset_train.jsonl", "deepset/deepset_test.jsonl",
    "prompts_chat/prompts_chat_train.jsonl",
    "advbench/advbench_train.jsonl",
    "jailbreakbench/jbb_behaviors_harmful.jsonl",
    "jailbreakbench/jbb_behaviors_benign.jsonl",
    "multijail/multijail_train.jsonl",
    "hh_rlhf/hh_rlhf_helpful_base_train.jsonl",
    "hh_rlhf/hh_rlhf_helpful_base_test.jsonl",
    "gandalf/gandalf_train.jsonl", "gandalf/gandalf_validation.jsonl",
    "gandalf/gandalf_test.jsonl",
    "xtram1/xtram1_train.jsonl", "xtram1/xtram1_test.jsonl",
]


# ============================================================
# 유틸
# ============================================================
def read_jsonl(path):
    """prompts.chat에 U+2028/U+2029 특수 줄바꿈이 있어 .splitlines() 금지."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def light_clean(text):
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def norm_for_dedup(text):
    return light_clean(text).lower()


def first_human_turn(chosen):
    if not chosen or "Human:" not in chosen:
        return None
    after = chosen.split("Human:", 1)[1]
    q = after.split("Assistant:", 1)[0]
    return q.strip() or None


# ============================================================
# 출처별 로더 -> (text, label, attack_type)
# ============================================================
def load_deepset():
    rows = []
    for fn in ["deepset_train.jsonl", "deepset_test.jsonl"]:
        for r in read_jsonl(RAW / "deepset" / fn):
            label = int(r["label"])
            rows.append((r["text"], label, "prompt_injection" if label == 1 else None))
    return rows


def load_advbench():
    return [(r["prompt"], 1, "harmful_instruction")
            for r in read_jsonl(RAW / "advbench" / "advbench_train.jsonl")]


def load_jbb():
    rows = []
    for r in read_jsonl(RAW / "jailbreakbench" / "jbb_behaviors_harmful.jsonl"):
        rows.append((r["Goal"], 1, "harmful_instruction"))
    for r in read_jsonl(RAW / "jailbreakbench" / "jbb_behaviors_benign.jsonl"):
        rows.append((r["Goal"], 0, None))
    return rows


def load_multijail():
    return [(r["en"], 1, "harmful_instruction")
            for r in read_jsonl(RAW / "multijail" / "multijail_train.jsonl") if r.get("en")]


def load_hh_rlhf():
    rows = []
    for fn in ["hh_rlhf_helpful_base_train.jsonl", "hh_rlhf_helpful_base_test.jsonl"]:
        for r in read_jsonl(RAW / "hh_rlhf" / fn):
            q = first_human_turn(r.get("chosen"))
            if q:
                rows.append((q, 0, None))
    return rows


def load_prompts_chat():
    rows, excluded = [], []
    for r in read_jsonl(RAW / "prompts_chat" / "prompts_chat_train.jsonl"):
        t = r.get("type")
        if t is not None and str(t).upper() != "TEXT":
            continue
        act = str(r.get("act", "")).lower()
        if any(bad in act for bad in PROMPTSCHAT_EXCLUDE):
            excluded.append(r.get("act", ""))
            continue
        if r.get("prompt"):
            rows.append((r["prompt"], 0, None))
    return rows, excluded


def load_gandalf():
    """Lakera/gandalf_ignore_instructions -> 전 행 공격(1) / prompt_injection.
    similarity 컬럼은 버린다. 저자가 라벨을 만들 때 쓴 기준값이라 피처로 쓰면 누수다.
    native split(train/validation/test)은 무시하고 풀링한다.
    한계: 공격에만 기여하는 출처이고 소재가 '비밀번호'에 편중돼 있다."""
    rows = []
    for fn in ["gandalf_train.jsonl", "gandalf_validation.jsonl", "gandalf_test.jsonl"]:
        for r in read_jsonl(RAW / "gandalf" / fn):
            rows.append((r["text"], 1, "prompt_injection"))
    return rows


def load_xtram1():
    """xTRam1/safe-guard-prompt-injection.

    label 0: 탈옥 혼입이 확인됨 -> jailbreak_hit()에 걸리면 제외(main에서 처리).
    label 1: 씨앗에 jackhhao/jailbreak-classification(탈옥)이 섞여 있어 순수 인젝션이 아니다.
             -> 버리지 않고 attack_type을 세분화한다.
                jailbreak 단서 有 -> "jailbreak"
                인젝션 단서 有   -> "prompt_injection"
                둘 다 無         -> "prompt_injection" (기본값, 보수적)

    ★ 평가 오염 주의: 난독화 평가셋(Mindgard)이 xTRam1에서 큐레이션됐다면,
      여기서 학습에 넣은 샘플이 평가셋의 원본이 된다. id/source를 보존해두고,
      평가셋 확정 후 반드시 안티조인으로 겹치는 학습 샘플을 제거할 것.
    """
    rows = []
    for fn in ["xtram1_train.jsonl", "xtram1_test.jsonl"]:
        for r in read_jsonl(RAW / "xtram1" / fn):
            label = int(r["label"])
            if label == 0:
                if not XTRAM1_INCLUDE_NORMAL:
                    continue
                rows.append((r["text"], 0, None))
            else:
                atype = "jailbreak" if jailbreak_hit(r["text"]) else "prompt_injection"
                rows.append((r["text"], 1, atype))
    return rows


LOADERS = {
    "deepset": load_deepset, "jailbreakbench": load_jbb, "advbench": load_advbench,
    "multijail": load_multijail, "hh_rlhf": load_hh_rlhf,
    "gandalf": load_gandalf, "xtram1": load_xtram1,
}


# ============================================================
def preflight():
    missing = [f for f in EXPECTED_FILES if not (RAW / f).exists()]
    if missing:
        print("[에러] 다음 raw 파일이 없습니다:")
        for m in missing:
            print("   -", RAW / m)
        raise SystemExit(1)


def main():
    preflight()
    OUT.mkdir(exist_ok=True)

    raw_rows = []
    per_source_loaded = Counter()
    excluded_pc = []
    drop_reason = Counter()          # (source, reason) -> n
    drop_samples = defaultdict(list)

    for src in SOURCE_ORDER:
        if src == "prompts_chat":
            rows, excluded_pc = load_prompts_chat()
        else:
            rows = LOADERS[src]()

        drop_langs = LANG_DROP_STRICT if src in LANG_STRICT_SOURCES else LANG_DROP_DEFAULT

        for text, label, atype in rows:
            cleaned = light_clean(text)
            if not cleaned:
                drop_reason[(src, "empty")] += 1
                continue

            lang = detect_lang(cleaned)
            if lang in drop_langs:
                drop_reason[(src, f"lang_{lang}")] += 1
                if len(drop_samples[(src, f"lang_{lang}")]) < 5:
                    drop_samples[(src, f"lang_{lang}")].append(cleaned[:110])
                continue

            # xtram1 정상에 섞인 탈옥 제외
            if src == "xtram1" and label == 0:
                hit = jailbreak_hit(cleaned)
                if hit:
                    drop_reason[(src, "normal_jailbreak")] += 1
                    if len(drop_samples[(src, "normal_jailbreak")]) < 5:
                        # 무엇이 걸렸는지 남긴다. 오탐 진단의 핵심.
                        drop_samples[(src, "normal_jailbreak")].append(
                            f'[매칭: "{hit}"] {cleaned[:100]}')
                    continue

            raw_rows.append({"text": cleaned, "label": label,
                             "source": src, "attack_type": atype})
            per_source_loaded[src] += 1

    # ---- 중복 제거 + 라벨 일관성 ----
    groups = defaultdict(list)
    for row in raw_rows:
        groups[norm_for_dedup(row["text"])].append(row)

    kept, conflicts, dup_removed = [], [], 0
    cross_dup = Counter()
    for members in groups.values():
        if len({m["label"] for m in members}) > 1:
            conflicts.append(members)
            continue
        winner = members[0]
        kept.append(winner)
        dup_removed += len(members) - 1
        for loser in members[1:]:
            if loser["source"] != winner["source"]:
                cross_dup[(winner["source"], loser["source"])] += 1

    for i, row in enumerate(kept):
        row["id"] = f"{row['source']}_{i:06d}"
        row["is_augmented"] = 0

    # ---- split 고정 (source×label 층화) ----
    rng = random.Random(SEED)
    by_group = defaultdict(list)
    for row in kept:
        by_group[(row["source"], row["label"])].append(row)
    for members in by_group.values():
        rng.shuffle(members)
        n_test = round(len(members) * TEST_RATIO)
        for j, row in enumerate(members):
            row["split"] = "test" if j < n_test else "train"

    with open(OUT / "combined.jsonl", "w", encoding="utf-8") as f:
        for row in kept:
            f.write(json.dumps({k: row[k] for k in SCHEMA}, ensure_ascii=False) + "\n")

    write_report(kept, conflicts, dup_removed, excluded_pc,
                 per_source_loaded, cross_dup, drop_reason, drop_samples)
    print(f"\n[완료] {OUT/'combined.jsonl'}  ({len(kept)}개)")
    print(f"[완료] {OUT/'build_report.md'}")


def write_report(kept, conflicts, dup_removed, excluded_pc,
                 per_source_loaded, cross_dup, drop_reason, drop_samples):
    total = len(kept)
    n_pos = sum(1 for r in kept if r["label"] == 1)
    n_neg = total - n_pos
    by_sl = Counter((r["source"], r["label"]) for r in kept)
    by_spl = Counter((r["split"], r["label"]) for r in kept)
    by_atype = Counter(r["attack_type"] for r in kept if r["label"] == 1)

    L = []
    L.append("# 정제·통합 리포트 (task 3)\n")
    L.append("> 클래스 균형(다운샘플)은 task 4. 아래 정상:공격 불균형은 **의도된 중간 상태**다.\n")

    L.append("\n## 요약\n")
    L.append(f"- 최종 유효 샘플: **{total}**개 (정상 {n_neg} / 공격 {n_pos})\n")
    ratio = (n_neg / n_pos) if n_pos else float("inf")
    L.append(f"- 정상:공격 비율 = **{ratio:.1f} : 1**\n")
    L.append(f"- 같은 라벨 중복 제거: {dup_removed}개\n")
    L.append(f"- 라벨 충돌로 제외: {sum(len(c) for c in conflicts)}개 ({len(conflicts)}그룹)\n")
    L.append(f"- prompts.chat 오염 제외: {len(excluded_pc)}개\n")

    L.append("\n## 사전 제외 내역 (dedup 이전)\n")
    L.append("| 출처 | 사유 | 개수 |\n|---|---|---|\n")
    for (src, reason), c in sorted(drop_reason.items()):
        L.append(f"| {src} | {reason} | {c} |\n")
    tot_drop = sum(drop_reason.values())
    L.append(f"\n- 사전 제외 합계: **{tot_drop}**개\n")
    L.append("\n> `lang_de` / `lang_mixed`: 영어 한정 규칙 적용. deepset은 en/de 병렬 코퍼스라\n")
    L.append("> strict(de+mixed), 나머지는 mixed 오탐이 많아 conservative(de만).\n")
    L.append("> `normal_jailbreak`: xtram1 정상(0)에 섞인 탈옥. 정상 클래스 오염 방지.\n")

    for key in sorted(drop_samples):
        L.append(f"\n**제외 표본 — {key[0]} / {key[1]}**\n\n")
        for s in drop_samples[key]:
            L.append(f"- {s}\n")

    L.append("\n## 출처별 로드→최종\n")
    L.append("| 출처 | 필터 후 로드 | 최종(정상0) | 최종(공격1) |\n|---|---|---|---|\n")
    for src in SOURCE_ORDER:
        L.append(f"| {src} | {per_source_loaded.get(src,0)} | "
                 f"{by_sl.get((src,0),0)} | {by_sl.get((src,1),0)} |\n")

    L.append("\n## split × 라벨 분포\n")
    L.append("| split | 정상0 | 공격1 |\n|---|---|---|\n")
    for sp in ["train", "test"]:
        L.append(f"| {sp} | {by_spl.get((sp,0),0)} | {by_spl.get((sp,1),0)} |\n")

    L.append("\n## 공격(label 1) attack_type 분포\n")
    L.append("| attack_type | 개수 |\n|---|---|\n")
    for atype, c in by_atype.most_common():
        L.append(f"| {atype} | {c} |\n")

    L.append("\n## 출처 지름길 점검\n")
    L.append("| 출처 | 정상0 | 공격1 | 상태 |\n|---|---|---|---|\n")
    for src in SOURCE_ORDER:
        a, b_ = by_sl.get((src, 0), 0), by_sl.get((src, 1), 0)
        if a and b_:
            state = "양쪽 기여"
        elif b_:
            state = "공격 전용 ⚠️"
        elif a:
            state = "정상 전용 ⚠️"
        else:
            state = "잔존 0"
        L.append(f"| {src} | {a} | {b_} | {state} |\n")

    if cross_dup:
        L.append("\n## 출처 간 교차 중복 (완전일치, 앞쪽 출처가 살아남음)\n")
        L.append("| 살아남은 출처 | 제거된 출처 | 건수 |\n|---|---|---|\n")
        for (win, lose), c in cross_dup.most_common(20):
            L.append(f"| {win} | {lose} | {c} |\n")

    if excluded_pc:
        L.append("\n## prompts.chat 제외 목록 (act)\n")
        for a in excluded_pc:
            L.append(f"- {a}\n")

    if conflicts:
        L.append("\n## 라벨 충돌 샘플 (최대 10건)\n")
        for members in conflicts[:10]:
            srcs = ", ".join(f"{m['source']}={m['label']}" for m in members)
            L.append(f"- [{srcs}] {members[0]['text'][:110]}\n")

    L.append("\n## 미해결 (마감 후 또는 한계로 기록)\n")
    L.append("- multijail↔advbench 근사 중복이 완전일치로는 0건. 출처 간 누수 가능성.\n")
    L.append("- gandalf는 공격 전용 + 소재가 '비밀번호'에 편중.\n")
    L.append("- 난독화 평가셋(Mindgard)이 xTRam1 유래라면, 확정 후 안티조인 필수.\n")

    (OUT / "build_report.md").write_text("".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()