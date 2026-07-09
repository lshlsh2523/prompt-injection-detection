# 난독화 평가셋(시험지) 빌드 리포트 (task 5)

- 총 3390개 (공격 1695 / 정상 1695), 1:1
- 출처: 공격=Mindgard(원본×기법균형) / 정상=잔여풀 15981개에서 길이매칭
- 공격 오염 재확인(original이 train에 있음): **0개** (기대 0)

## 길이 매칭 (공격 vs 정상)

- 공격 길이 중앙값 111 / 정상 중앙값 108
| 길이구간 | 공격필요 | 정상확보 | 근사중복제거 | 풀크기 |
|---|---|---|---|---|
| 0-60 | 9 | 9 | 37 | 7248 |
| 60-120 | 924 | 924 | 2818 | 3841 |
| 120-200 | 391 | 331 | 1154 | 1485 |
| 200-300 | 88 | 88 | 415 | 1324 |
| 300-600 | 82 | 82 | 303 | 812 |
| 600-∞ | 370 | 261 | 1010 | 1271 |

## 공격 기법 분포 (20기법 골고루 확인)

| attack_name | 개수 |
|---|---|
| Alzantot | 94 |
| BAE | 94 |
| Bert-Attack | 94 |
| Bidirectional Text | 94 |
| Deep Word Bug | 93 |
| Deletion Characters | 93 |
| Diacritcs | 93 |
| Emoji Smuggling | 93 |
| Full Width Text | 93 |
| Homoglyphs | 93 |
| Numbers | 93 |
| PWWS | 93 |
| Pruthi | 93 |
| Spaces | 93 |
| TextBugger | 93 |
| TextFooler | 93 |
| Underline Accent Marks | 93 |
| Unicode Tags Smuggling | 93 |
| Upside Down Text | 93 |
| Zero Width | 93 |

## 한계 (일지)
- 다양성 상한은 원본 623개. 기법으로 부풀려도 밑바탕은 623 시나리오.
- 라이선스 cc-by-nc-4.0(비상업)·gated → jsonl 은 공개레포에 올리지 말 것(빌드스크립트만 커밋).
- 내부 test 성능과 이 평가셋 성능을 절대분리해 해석(분포 다름).
