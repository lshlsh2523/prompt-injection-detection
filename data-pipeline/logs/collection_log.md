# 데이터셋 수집 로그

> 원본 수집 기록. 정제·라벨링 전 "받은 그대로"의 상태를 기록한다.
> 행 수가 시점마다 변하는 데이터셋(prompts.chat 등)은 받은 날 스냅샷이 기준이다.

## 수집 현황

| # | 데이터셋 | HF 경로 | split | 행 수 | 저장 파일 | 수집일 | 비고 |
|---|---|---|---|---|---|---|---|
| 1 | Deepset Prompt Injections | `deepset/prompt-injections` | train / test | 546 / 116 (합 662) | `raw/deepset/deepset_{train,test}.jsonl` | 2026-07-02 | 이미 0/1 라벨 있음. 자체 train/test 분리됨 |
| 2 | prompts.chat | `fka/prompts.chat` | train | 1943 | `raw/prompts_chat/prompts_chat_train.jsonl` | 2026-07-02 | 라이브 미러(행 수 변동). type=TEXT/STRUCTURED/IMAGE 혼재 |
| 3 | AdvBench | `walledai/AdvBench` | train | 520 | `raw/advbench/advbench_train.jsonl` | 2026-07-02 | gated(접근 동의 필요). target 컬럼 있음(정제 시 제거). JBB와 중복 있음 |
| 4 | JailbreakBench (JBB-Behaviors) | `JailbreakBench/JBB-Behaviors` (behaviors) | harmful / benign | 100 / 100 | `raw/jailbreakbench/jbb_behaviors_{harmful,benign}.jsonl` | 2026-07-02 | 공식 원본. judge_comparison은 변형 프롬프트라 제외. 컬럼 대문자(Goal/Source). harmful→1, benign→0 |
| 5 | MultiJail | `DAMO-NLP-SG/MultiJail` | train | 315 | `raw/multijail/multijail_train.jsonl` | 2026-07-02 | 공식 원본. 9개 언어 병렬. en 컬럼만 사용(→1). source 컬럼 있음(중복 제거용) |
| 6 | Anthropic hh-rlhf | `Anthropic/hh-rlhf` (helpful-base) | train / test | 43835 / 2354 | `raw/hh_rlhf/hh_rlhf_helpful_base_{train,test}.jsonl` | 2026-07-02 | helpful-base 서브셋만(harmless/red-team 제외). chosen/rejected는 답변만 다름 |

## 정제 단계로 넘길 메모

- **prompts.chat**
  - `type` 필터: `TEXT`만 사용, `STRUCTURED`·`IMAGE` 제외 검토
  - 오염 샘플 주의: "AI Trying to Escape the Box"(탈옥 프레이밍), "Gaslighter"(조작) 등 — 정상(0)에 넣으면 안 됨. 라벨 규칙(의도·기능 기준)으로 재검토 후 제외/플래그
  - 파일 읽을 때 `.splitlines()` 금지(LS·PS로 줄 쪼개짐) → `for line in f:` 또는 `json.loads`로
  - 사용할 컬럼: `prompt` (본문). `act`/`for_devs`/`contributor`는 메타
- **Deepset**
  - 자체 train/test 분리가 있음 → 통합 시 이걸 유지할지, 무시하고 우리 기준으로 다시 나눌지 정제 단계에서 결정
- **AdvBench**
  - `target` 컬럼 제거(우리는 `prompt`만 사용)
  - JBB와 중복 제거 필수 (다음에 받을 JailbreakBench와 교차 확인) 
- **JailbreakBench (JBB-Behaviors)**
  - 텍스트 컬럼은 `Goal` (대문자 주의). `Target`은 버림
  - `harmful` split → label 1, `benign` split → label 0
  - `harmful`의 `Source == "AdvBench"` 행은 AdvBench와 중복 → 중복 제거 대상
  - judge_comparison subset은 GCG/PAIR 변형 프롬프트라 학습 제외 (필요시 난독화 평가셋 후보로만)
- **MultiJail**
  - `en` 컬럼만 사용(→ label 1). 나머지 언어 컬럼은 버림(영어 단일 모델)
  - en 315개 중 ~300개가 Anthropic red-team 출신 → AdvBench/JBB/hh-rlhf와 `source` 컬럼으로 중복 교차 확인
