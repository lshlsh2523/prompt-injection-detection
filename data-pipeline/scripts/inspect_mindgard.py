#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_mindgard.py
Mindgard/evaded-prompt-injection-and-jailbreak-samples 조사용 (읽기 전용, 저장 안 함).

목적
  (1) 구조/규모/컬럼 확인  (2) attack_name 별 개수  (3) emoji smuggling(Base64) 식별
  (4) original vs modified 길이 분포 (Base64는 디코드한 '실질 텍스트' 기준으로 측정)
  (5) 겹침 제거에 쓸 정규화 함수(norm)를 여기서 미리 검증 (다음 단계에서 재사용)

주의
  - 이 데이터셋의 split 이름이 'train'이어도 그건 HF 기본 이름일 뿐,
    우리 프로젝트에선 전량 '평가 전용'이다. train/test 배정과 무관.
  - injected unicode(zero-width 등)가 있어 예시는 repr()로 출력해 특수문자를 노출한다.

실행
  python scripts/inspect_mindgard.py --selftest   # 먼저 로직 검증
  python scripts/inspect_mindgard.py              # 실데이터 조사
"""
import sys
import re
import base64
import statistics
from collections import Counter, defaultdict

DATASET = "Mindgard/evaded-prompt-injection-and-jailbreak-samples"


def norm(text):
    """겹침 비교용 정규화: 공백 단일화 + strip + 소문자.
    clean_integrate.py 의 norm_for_dedup 과 동일 규칙(다음 단계에서 이 키로 xtram과 대조)."""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def try_b64_decode(s):
    """문자열이 통째로 Base64면 디코드한 utf-8 문자열을, 아니면 None.
    (평범한 영어 문장은 공백/구두점 때문에 대부분 걸러지지만,
     알파벳만 있는 짧은 단어가 우연히 통과할 수 있어 attack_name과 교차로 봐야 함.)"""
    t = str(s).strip()
    if len(t) < 8 or len(t) % 4 != 0:
        return None
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", t):
        return None
    try:
        return base64.b64decode(t, validate=True).decode("utf-8")
    except Exception:
        return None


def eff_text(modified):
    """길이 측정용 '실질 텍스트': Base64면 디코드본, 아니면 원문."""
    dec = try_b64_decode(modified)
    return dec if dec is not None else str(modified)


def stats(vals):
    vals = sorted(vals)
    return (vals[0], int(statistics.median(vals)),
            round(statistics.mean(vals)), vals[-1])


def selftest():
    # norm
    assert norm("  Ignore   ALL\nprevious ") == "ignore all previous"
    # base64 왕복: "hello" -> "aGVsbG8="
    enc = base64.b64encode("hello".encode()).decode()
    assert try_b64_decode(enc) == "hello"
    # 공백/구두점 있는 문장은 Base64로 오인되면 안 됨
    assert try_b64_decode("Ignore all previous instructions.") is None
    # eff_text
    assert eff_text(enc) == "hello"
    assert eff_text("plain text here") == "plain text here"
    # stats
    assert stats([1, 2, 3, 10]) == (1, 2, 4, 10)
    print("[selftest] 통과: norm / try_b64_decode / eff_text / stats")


def inspect():
    try:
        from datasets import load_dataset
    except ImportError:
        print("[에러] datasets 미설치 → pip install datasets")
        sys.exit(1)

    try:
        ds = load_dataset(DATASET)
    except Exception as e:
        print("[에러] 로드 실패:", repr(e))
        print(">> gated 데이터셋이야. 브라우저에서 HF 로그인 후 아래 페이지에서")
        print("   조건 수락(Agree and access)을 먼저 눌러야 토큰으로 받아져:")
        print("   https://huggingface.co/datasets/" + DATASET)
        sys.exit(1)

    print("=== splits (이름이 train이어도 우리에겐 전량 평가용) ===")
    for split in ds:
        print(f"  {split}: {len(ds[split])} rows")

    first = list(ds.keys())[0]
    print("=== columns ===", ds[first].column_names)

    rows = [r for split in ds for r in ds[split]]
    print(f"=== 전체 {len(rows)} rows ===\n")

    # attack_name 구성
    ac = Counter(r.get("attack_name", "?") for r in rows)
    print("=== attack_name 별 개수 ===")
    for k, v in ac.most_common():
        print(f"  {v:6d}  {k}")

    # attack_name 별 Base64 디코드 가능 비율 → emoji smuggling 식별
    print("\n=== attack_name 별 modified의 Base64 디코드 비율 ===")
    b64tab = defaultdict(lambda: [0, 0])
    for r in rows:
        an = r.get("attack_name", "?")
        b64tab[an][1] += 1
        if try_b64_decode(r.get("modified_sample", "")) is not None:
            b64tab[an][0] += 1
    for an, (dec, tot) in sorted(b64tab.items()):
        print(f"  {dec:5d}/{tot:<5d} ({dec / tot * 100:5.1f}%)  {an}")

    # 길이 분포 (실질 텍스트 기준)
    olens = [len(str(r.get("original_sample", ""))) for r in rows]
    mlens = [len(eff_text(r.get("modified_sample", ""))) for r in rows]
    print("\n=== 길이(문자수) [min / median / mean / max] ===")
    print(f"  original       : {stats(olens)}")
    print(f"  modified(실질) : {stats(mlens)}")
    long_ratio = sum(1 for x in mlens if x >= 300) / len(mlens) * 100
    print(f"  modified 300자+ 비율: {long_ratio:.1f}%   "
          f"(우리 정상 클래스 장문비율 ~8% 와 비교해 길이 편향 가늠)")

    # 예시 3개 (repr로 zero-width/homoglyph 노출)
    print("\n=== 예시 (repr) ===")
    for r in rows[:3]:
        print(f"  [{r.get('attack_name','?')}]")
        print(f"    original: {str(r.get('original_sample',''))[:90]!r}")
        print(f"    modified: {str(r.get('modified_sample',''))[:90]!r}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        inspect()