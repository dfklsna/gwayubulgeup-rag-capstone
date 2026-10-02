# 과유불급 — 음식·카페인·비타민 섭취 분석 RAG

먹은 음식의 양이나 제품에 표시된 성분 함량을 입력하면, 영양성분을 계산하고 공식 자료의 조건별 기준과 함께 설명하는 프로젝트입니다. 음식 DB 조회와 수치 계산은 Python이 담당하고, LLM은 자연어 입력 구조화와 검색 근거를 활용한 설명을 담당합니다.

Baseline RAG를 구현한 뒤 검색·답변 처리 방법 7가지를 비교하고, 새 질문에서 발견한 오류를 바탕으로 입력 검증과 근거 처리를 개선했습니다. 설계 과정, 실험 결과, 남은 한계를 함께 공개합니다.

## 주요 기능

- **음식 영양성분 계산:** 식품코드와 섭취량으로 성분량을 계산합니다. 같은 이름의 음식이 여러 개면 출처·단위를 보여주고 선택을 요청합니다.
- **카페인·비타민 기준 비교:** 표시 함량과 개수를 계산하고 대상 조건에 맞는 기준을 조회합니다. 정보가 부족하면 추가 입력을 요청합니다.
- **근거 추적:** 답변에 검색 문서의 URL·페이지와 계산 내역을 남깁니다.
- **입력 검증:** 원문 전체, 프로필, 성분명과 ID, 수치·단위·개수의 연결을 확인하고 불명확한 입력은 계산을 보류합니다.

## 빠르게 실행하기

Python 3.12 기준입니다. API 키나 별도 패키지 없이 가상 데이터 계산을 먼저 확인할 수 있습니다.

```bash
git clone https://github.com/dfklsna/gwayubulgeup-rag-capstone.git
cd gwayubulgeup-rag-capstone
python src/capstone_compare.py --demo
```

가상 음식 200g의 에너지 160kcal·나트륨 60mg이 출력됩니다. 실제 영양 기준이나 검색·생성까지 실행하려면 아래 설치와 데이터 준비가 필요합니다. 명령 목록은 `python src/capstone_compare.py --help`로 확인할 수 있습니다.

## 데이터와 설계

- 검색: 최신 정제 문서136개·8,308청크, 페이지 보존, 1,500자/겹침200자, 정규화 cosine Top-5. 과거63문서는 기본 검색 제외.
- 계산: 음식19,617건·성분134열, KDRI 조건별 기준4,641행(미설정 포함), 카페인 권고3개.
- 현재 구성: 주제 필터 + 결정적 계산·확인 안내 + 인용 ID 검사 + 검증된 개념4종. 일반 LLM 근거 재검토는 회귀로 비활성화.
- 초기 수집은 더 넓은 건강 주제를 포함했습니다. 냉수욕·수중침수는 현재 영양 기능 범위 밖이며 코퍼스 전체를 영양 전용으로 다시 선별한 것은 아닙니다.

[설계](results/design.md) · [데이터 준비](data/README.md) · [실행 예시](docs/DEMO.md). 실제 원문·DB·인덱스·키는 공개 저장소에 포함하지 않습니다.

## 설치와 전체 데이터 실행

Python3.12 기준입니다.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/configure_api_key.py
```

macOS는 숨김 키 입력 창, 다른 운영체제는 터미널 숨김 입력을 사용합니다. 키는 로컬 `.env`에 저장합니다. 기본 모델은 `gpt-4.1-mini-2025-04-14`, 임베딩은 `text-embedding-3-small`입니다. `.env`의 비어 있지 않은 값이 셸 설정보다 우선하고 빈 예시 변수는 셸 값을 지우지 않습니다.

[data 준비](data/README.md)를 완료한 뒤 실행합니다. 전체 수집 자료가 자동 복원되는 구성은 아닙니다.

```bash
python scripts/prepare_caffeine_rules.py
python src/capstone_compare.py prepare
python src/capstone_compare.py foods '해파리냉채'
python src/capstone_compare.py calculate --request examples/jellyfish_400g.json
python src/capstone_compare.py build
python src/capstone_compare.py ask --request examples/caffeine_450mg.json
python src/capstone_compare.py ask --question '커피 세 잔 마셨는데 카페인 과다야?'
```

`prepare`, `foods`, `calculate`는 API 없이 동작합니다. `build`는 본문을 임베딩 API로 보내며 유료 사용량이 발생합니다. `ask`는 질문 임베딩·일반 답변 생성, 자연어라면 입력 구조화 API를 사용합니다. 입력 섭취·프로필 정보가 해당 호출에 포함되며 Responses는 `store=False`로 호출합니다. 기본 `ask`는 선택 조합이고 `--variant baseline`으로 Baseline을 실행합니다. 결과 JSON에는 답변·근거 URL/페이지·계산 내역이 있습니다.

## API 없이 공개 소스 검증

```bash
python -m unittest discover -s tests -v
python scripts/make_demo.py
RAG_DATA_DIR=data/demo RAG_CACHE_DIR=data/demo/index python src/capstone_compare.py calculate --request examples/demo.json
```

전체 자료 없는 공개 clone에서는 테스트 102개 중 99개가 통과하고 실제 데이터가 필요한 3개는 건너뜁니다. 실제 데이터 환경에서는 102개 모두 통과했습니다. 가상 DB에는 실제 영양소 기준이 없습니다.

## 비교와 재평가

개발12문항에서 Baseline source Recall@5는6/8, 주제 필터+계산·확인+인용 검사 조합은8/8이었습니다. 검색 점수는 답변 정확도가 아닙니다. 이후 새24문항에서14충족·5부분·5실패를 기록했고 원문 검증·제한된 개념 처리를 보완했습니다. 현재 내용 검토 결과는 기존 24문항 22충족·1부분·1실패, 개발 12문항 9충족·3부분, 기존 관계 4문항 3충족·1실패(계산 보류), 추가 진단 4문항 4충족입니다. 소규모 비맹검 assistant 검토이며 전문가 검증이나 일반적인 답변 정확도를 의미하지 않습니다.

단계별 실험과 남은 오류는 [평가 문서](results/evaluation.md), 수치와 문항별 판단은 [평가 집계](results/integrity_summary.json)에 있습니다.

```bash
python src/capstone_compare.py evaluate --questions examples/evaluation_questions.jsonl --output results/runs/my_baseline
python src/capstone_compare.py compare --baseline results/runs/my_baseline --output results/comparisons/my_ablation
python scripts/evaluate_holdout.py --questions examples/holdout_questions_24.jsonl --plan examples/integrity_regression_plan.json --output results/holdout/my_review
```

7개 단독 방법은 hybrid, mmr, rerank, topic_filter, compression, guard, citations입니다. 전체 데이터·API가 필요하고 기존 결과를 덮어쓰지 않습니다. 정답 출처를 모델에 넣지 않으며 답변 내용 검토는 자동 지표와 별도로 수행합니다.

## 범위와 한계

한 번에 한 음식/성분을 계산합니다. 동명 음식은 식품코드 선택, 카페인은 표시 함량·개수, 조건별 기준은 인적 조건이 필요합니다. RNI/EAR/AI 초과를 과다로 판정하지 않으며 미확보 성분을0으로 바꾸지 않습니다. 밀도 없는 부피/질량 환산, IU·비타민 A/E의 형태 불명 상한 비교, 여러 항목의 실제 하루 합산, 개인 진단·처방 변경은 지원하지 않습니다.

관계 검증은 제한된 문장 구조를 대상으로 하며 정상 입력도 보류할 수 있습니다. 이번 실행에서 카페인2캔·비타민C 총량 질문은 추출 불일치로 보류됐습니다. 음식명은 등록명·별칭과 코드가 일치해야 하며 미등록 이름은 정상 음식이어도 확인을 요청합니다. 커피 잔 수를 음식으로 추출하면 카페인 표시 함량 안내가 부족할 수 있습니다. 일반 설명의 근거 함의·적용 범위·불필요한 인용 문제도 남아 있습니다. OCR3개 출처, EFSA부록8개, 모든 표·그림 전수 검토는 미완료입니다. [공개 범위](docs/PUBLISHING.md)를 참고하세요.
