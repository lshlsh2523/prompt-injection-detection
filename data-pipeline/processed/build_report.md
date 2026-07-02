# 정제·통합 리포트 (task 3)
> 클래스 균형(다운샘플)은 task 4에서 함. 아래 정상:공격 불균형은 **의도된 중간 상태**다.
## 요약
- 최종 유효 샘플: **19170**개  (정상 0 = 17986 / 공격 1 = 1184)
- 정상:공격 비율 = **15.2 : 1**  (불균형 정상 — task 4에서 조정)
- 같은 라벨 중복 제거: 30331개
- 라벨 충돌로 제외: 6개 (3그룹) — **팀 검토 필요**
- prompts.chat 오염 제외: 2개

## 출처별 로드→최종 (중복/충돌 제거 전후)
| 출처 | 클리닝 후 로드 | 최종(정상0) | 최종(공격1) |
|---|---|---|---|
| deepset | 662 | 399 | 260 |
| jailbreakbench | 200 | 100 | 100 |
| advbench | 520 | 0 | 509 |
| multijail | 315 | 0 | 315 |
| prompts_chat | 1621 | 1617 | 0 |
| hh_rlhf | 46189 | 15870 | 0 |

## split × 라벨 분포
| split | 정상0 | 공격1 |
|---|---|---|
| train | 14389 | 947 |
| test | 3597 | 237 |

## prompts.chat 제외 목록 (act)
- AI Trying to Escape the Box
- Gaslighter

## 라벨 충돌 샘플 (최대 10건, 검토용)
같은 텍스트가 서로 다른 출처에서 정상/공격으로 라벨됨 → 전부 제외함.

- [deepset=1, prompts_chat=0] I want you to act as a debater. I will provide you with some topics related to current events and your task is to resear
- [deepset=1, prompts_chat=0] I want you to act as a linux terminal. I will type commands and you will reply with what the terminal should show. I wan
- [deepset=1, prompts_chat=0] I want you to act as an English translator, spelling corrector and improver. I will speak to you in any language and you
