# 과유불급 — 영양 정보 RAG 개선 비교

음식 섭취량·카페인·비타민 함량을 정량 계산하고, 공식 근거를 찾아 영양소 섭취기준과 구분해 설명하는 RAG 실습입니다. 식품 DB 계산과 조건별 기준 조회는 Python이 수행하고, LLM은 계산 결과와 검색 문서를 받아 답변합니다.

**현재 상태:** 남은 설명 오류를 검증된 개념 조회와 코드 환산으로 제한하고 제출 버전을 평가했습니다. 기존24문항은 assistant 검토에서24개 충족, 미사용8문항도8개 충족했습니다. 처음12문항에는 불필요한 인용2개가 남아 있습니다. 이 결과는 소규모 비맹검 평가이며 일반 영양 질문의 정확도100%를 뜻하지 않습니다. [최신 평가](results/evaluation.md) · [공개 집계](results/release_summary.json) · [실행 예시](docs/DEMO.md).

## 사용 데이터와 구조

- 검색: 최신 정제 문서 136개 → 페이지를 보존한 1,500자 청크(겹침 200자) → OpenAI 임베딩 → FAISS cosine Top-5 → LLM.
- 계산: 음식 DB 19,617건, KDRI 조건별 기준 4,641건(미설정 행 포함), 카페인 대상별 권고 3개.
- 과거 자료 63개는 기본 검색에서 제외합니다. 대용량 데이터는 저장소에 포함하지 않습니다.
- 설계: [results/design.md](results/design.md), 평가: [results/evaluation.md](results/evaluation.md), 출처와 준비: [data/README.md](data/README.md).

## 설치

Python 3.12 기준입니다. 프로젝트 루트에서 실행합니다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/configure_api_key.py
```

macOS에서는 가려진 키 입력 창이 열리고, 다른 운영체제에서는 터미널의 숨김 입력을 사용합니다. 키는 로컬 `.env`에 저장됩니다. 비어 있지 않은 파일 설정이 셸 환경변수보다 우선하고, 빈 예시 변수는 셸 설정을 지우지 않습니다. 빈 모델 변수는 기본값 `gpt-4.1-mini-2025-04-14`와 `text-embedding-3-small`을 사용합니다. 키를 GitHub나 채팅에 올리지 마세요. 모델을 변경하면 동일 비교 실험에도 일관되게 적용해야 합니다.

## API 없이 공개 예제 실행

```bash
python scripts/make_demo.py
RAG_DATA_DIR=data/demo RAG_CACHE_DIR=data/demo/index python src/capstone_compare.py calculate --request examples/demo.json
python -m unittest discover -s tests -v
```

가상음식 200g의 계산값이 출력됩니다. 예제는 실제 영양 기준을 포함하지 않아 기준 비교를 요청하면 추가 정보가 필요하다고 표시합니다. 전체 자료가 없는 clone에서는 실제 DB에 대한 테스트 2개가 skip됩니다.

## 전체 로컬 데이터 실행

[data 준비](data/README.md) 후 다음을 실행합니다.

```bash
python scripts/prepare_caffeine_rules.py
python src/capstone_compare.py prepare
python src/capstone_compare.py foods '해파리냉채'
python src/capstone_compare.py calculate --request examples/jellyfish_400g.json
python src/capstone_compare.py calculate --request examples/caffeine_450mg.json
python src/capstone_compare.py calculate --request examples/vitamin_c_2000mg.json
python src/capstone_compare.py build
python src/capstone_compare.py ask --request examples/jellyfish_400g.json
python src/capstone_compare.py ask --question '커피 세 잔 마셨는데 카페인 과다야?'
```

`prepare`, `foods`, `calculate`는 API를 호출하지 않습니다. `build`는 문서 전체를 임베딩 API로 전송하며 유료 사용량이 발생합니다. 청크 32개 단위로 캐시하여 중단 후 재실행할 수 있습니다. `ask`는 질문 임베딩·답변 생성, 자연어 입력이면 입력 구조화 API도 호출합니다. 입력한 섭취·프로필 정보는 해당 호출에 포함됩니다. Responses 호출은 `store=False`로 설정합니다.

`ask`는 최종 조합이 기본값이며 초기 동작은 `--variant baseline`으로 실행합니다. `ask`의 JSON에는 답변, Top-5 문서와 점수, 원문 URL·물리 PDF 페이지, 계산 근거가 포함됩니다. `[D1]`은 검색 문서, `[T1]`은 계산 결과입니다. 실험 결과를 남기려면 `--output results/runs/example.json`을 사용합니다.

## 평가와 개선

다음 12개 질문을 고정해두었습니다: [evaluation_questions.jsonl](examples/evaluation_questions.jsonl). 정답형·표현 변경·키워드·복합·근거 없음·확인 질문·기준 해석을 포함합니다.

```bash
python src/capstone_compare.py evaluate --questions examples/evaluation_questions.jsonl --output results/runs/baseline_02
```

정답 출처는 검색/생성 입력에 주입하지 않습니다. source ID 단위 Recall@5를 자동 기록하고, 근거 없는 질문은 분모에서 제외합니다. 최초 실행 `baseline_01`은 보존되어 있어 재실행은 새 출력 경로를 사용합니다. 정답 passage 포함 여부와 답변의 근거 일치·정확성·문제점에 대한 assistant 1차 검토를 기록했으며 사용자/전문가 검토는 미완료입니다. 전체 답변 정확도 점수로 해석하지 않습니다. 실패 사례와 7개 개선 방법의 전후 결과는 평가 문서에 있습니다.

## 지원 범위와 한계

동일 음식명의 조리법·출처가 여러 개면 사용자가 식품코드를 선택해야 합니다. 커피 잔 수만으로 카페인 양을 추정하지 않으며, 제품 표시 함량과 개수로 계산할 수 있습니다. 예제의 인적 조건은 가상의 테스트 조건입니다.

Baseline은 한 번에 음식 또는 성분 한 항목만 계산합니다. 여러 식품·보충제의 하루 합산, 복용 스케줄, 개인 질환별 진단은 지원하지 않습니다. RNI/EAR/AI를 과다 기준으로 쓰지 않습니다. 단위가 다른 질량·부피, IU, 비타민 A·E의 형태별 상한 비교는 자동으로 변환·판정하지 않습니다. 성분 미기재는 0으로 간주하지 않습니다.

OCR 3개 출처, EFSA 부록 8개, 모든 표·그림의 전수 검토는 남아 있습니다. 이 제한을 포함한 실제 데이터 준비 상태는 설계 문서에 기록했습니다. [GitHub 공개 준비](docs/PUBLISHING.md)를 참고하세요.

## 7개 개선 방법 비교와 최종 구성

단독 비교를 실행하려면 완성한 Baseline 기록이 필요합니다. 아래 출력 경로가 이미 있다면 새 이름을 사용하세요.

```bash
python src/capstone_compare.py compare --baseline results/runs/baseline_01 --output results/comparisons/my_ablation
python src/capstone_compare.py compare --variants combined --output results/comparisons/my_combined
python src/capstone_compare.py ask --variant combined --request examples/jellyfish_400g.json
python src/capstone_compare.py ask --variant combined --question '커피 세 잔 마셨는데 카페인 과다야?'
```

단독 방법은 `--variants hybrid mmr rerank topic_filter compression guard citations`입니다. 중단 후 같은 경로에 `--resume`을 지정하면 설정을 대조하고 완료된 결과를 보존합니다. 코드가 바뀌었으면 재개 이력과 새 스냅샷도 기록됩니다. 변경 내용을 검토하고 사용해야 합니다.

최종 선택은 `examples/selected_strategy.json`의 **주제 필터 + 계산·확인 강화 + 인용 검증**입니다. 단독 실험과 조합 실험은 같은 12개 질문, 같은 모델, 같은 데이터, Baseline에서 추출한 동일 입력을 사용했습니다. 검색·생성 방식별 원시 결과는 로컬에 남기고 공개용 집계는 `results/comparison_summary.json`에 저장합니다.

주제 필터/최종 조합의 출처 Recall@5는 8/8=100%였지만 **최종 답변 정확도 100%를 뜻하지 않습니다.** 일반 설명 질문의 상한섭취량 해석 오류가 남아 있습니다. 실제 섭취 항목 5문항은 LLM이 아닌 코드로 결과를 설명합니다. 방법별 효과와 회귀는 [평가 기록](results/evaluation.md)을 확인하세요. 이 질문 집합은 설정 선택에 사용한 개발 평가셋이며 독립 검증셋이 아닙니다.


## 새로운 질문 24개 검증

음식·카페인·비타민·예외 상황 각 6개를 [새 질문 파일](examples/holdout_questions_24.jsonl)에 고정하고, 자연어 해석부터 최종 답변까지 기존 최종 조합으로 실행했습니다. [평가 계획](examples/holdout_plan.json)과 [공개 결과](results/holdout_summary.json)를 함께 제공합니다.

```bash
python scripts/evaluate_holdout.py --output results/holdout/my_new_run
```

전체 로컬 데이터와 API 설정이 필요하며 이미 존재하는 출력 폴더에는 쓰지 않습니다. 정답은 모델 입력에 주입하지 않습니다. 이 명령은 자동 지표를 생성하고, 답변 내용 검토는 별도로 수행해야 합니다.

24문항 모두 실행됐고 출처 검색은 13/13, 숫자 체크는 9문항의 27/27을 통과했습니다. 그러나 assistant 내용 검토는 **충족 14개·부분 충족 5개·실패 5개**였습니다. 음수 부호·단위·섭취 의도 추출 오류, 다른 성분의 근거 사용, 나트륨/소금 설명 모순이 발견됐습니다. 코드를 수정하기 전의 결과이며 전문가 검증은 아닙니다. 기존 12문항 점수와 합쳐 답변 정확도로 표시하지 않습니다.


## 입력 오류 수정 후 최종 구성

원문의 음수·0, 수치·단위·개수 불일치를 검사하고 실제 섭취와 가정·답변 지시를 구분합니다. `ug_RAE` 등 단위를 보존하며, 잘못 추출한 항목이 있으면 계산을 보류합니다. UL 미설정과 수유 조건의 안내도 보완했습니다. 처방 변경·근거 조작 요구는 서비스 범위 안내로 처리합니다.

기본 구성은 주제 필터 + 계산·확인 강화 + 인용 검증입니다. 추가 근거 선택·검토 실험은 정상 답변 삭제 회귀로 제외했습니다(`evidence_review=false`). 해당 실험 기능을 켜면 추가 모델 호출이 발생하며 검증된 기본 기능으로 간주하지 않습니다.

```bash
python scripts/evaluate_holdout.py --questions examples/holdout_questions_24.jsonl --plan examples/revision_evaluation_plan_final.json --output results/holdout/my_regression
python scripts/evaluate_holdout.py --questions examples/fresh_questions_final_4.jsonl --plan examples/revision_evaluation_plan_final.json --output results/holdout/my_extra_check
python -m unittest discover -s tests -v
```

최종 버전으로 기존24·처음12·추가8의 회귀 평가와 미사용4문항 점검을 완료했습니다. 미사용4문항은 입력·계산 위주의 작은 비맹검 표본이며 일반 설명의 정확도를 대표하지 않습니다. 이전의 새24 및 중간에 사용한 새12·8은 현재 개발/회귀 질문입니다. 과거 결과는 역사적 기록으로 보존했습니다.

36개 자동 테스트가 통과했고 전체 DB 없는 공개 복사본에서는34개 통과·2개 skip 및 가상 데이터 계산을 확인했습니다. 제출 진입점은 `src/capstone_compare.py`, 설계/평가는 `results/design.md`·`results/evaluation.md`이며 실행에는 `src/experiments.py`와 DB 조회 스크립트도 필요합니다. 공개 저장소는 [dfklsna/gwayubulgeup-rag-capstone](https://github.com/dfklsna/gwayubulgeup-rag-capstone)입니다.


## 제출 버전의 제한된 개념 설명

`bounded_concepts=true`는 기준 종류, 당류 구분, 카페인 급원 합산, 소금 환산을 검증한 출처·고정 설명·코드 계산으로 처리합니다. 필요한 원문이 없거나 해시가 달라지면 답변을 보류합니다. 소금은 나트륨의 약2.5배라는 근사 환산이며 실제 제품 조성 측정값과 구분합니다. 이 기능은 일반 생성 전체를 검증하는 기능이 아닙니다.

```bash
python scripts/evaluate_holdout.py --questions examples/release_fresh_questions_8.jsonl --plan examples/release_evaluation_plan.json --output results/holdout/my_release_check
python scripts/package_release.py --output tmp/my_release
```

이 평가에는 전체 로컬 데이터와 API 설정이 필요합니다. 공개 묶음의 오프라인 데모는 전체 데이터를 요구하지 않습니다. [제출 안내](docs/SUBMISSION.md)와 [공개 준비](docs/PUBLISHING.md)를 확인하세요. 아래/위의 이전 평가 절은 실험 이력으로 보존하며 최신 결과는 `release_summary.json`입니다.

제출 버전 검증: 로컬44개 테스트 통과, 공개 복사본41개 통과·실데이터용3개 skip, API 없는 가상 음식 예제 성공. 소스 묶음의 파일 해시와 키·원문·DB 제외도 확인했습니다.
