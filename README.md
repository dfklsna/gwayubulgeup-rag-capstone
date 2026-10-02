# 과유불급 — 영양 정보 RAG 개선 비교

음식 섭취량·카페인·비타민 함량을 계산하고 공식 근거와 조건별 기준을 함께 설명하는 RAG 실습입니다. Python이 DB 조회·계산을 담당하고 LLM이 입력 구조화와 일반 설명을 담당합니다.

**현재 제출 점검:** 개수 누락과 체중/음식량 혼동을 수정했습니다. 실제 데이터 환경에서 53개 테스트가 통과했습니다. 내용 검토는 기존24문항 23충족·1부분, 개발12문항 10충족·2부분, 추가4문항 3충족·1실패(계산 보류)입니다. 과거 결과와 구분한 [평가 문서](results/evaluation.md)와 [현재 집계](results/submission_review_summary.json)를 확인하세요. 소규모 비맹검 assistant 검토이며 전체 답변 정확도나 전문가 검증이 아닙니다.

## 세 파일만으로 실행

필수 제출 파일은 `src/capstone_compare.py`, `results/design.md`, `results/evaluation.md`입니다. 진입점에 직접 작성한 보조 코드·설정이 내장되어 있어 세 파일만 받은 환경에서도 다음 명령이 동작합니다.

```bash
python src/capstone_compare.py --help
python src/capstone_compare.py --demo
python src/capstone_compare.py --requirements
```

세 파일을 같은 폴더에 두었다면 `src/`를 빼세요. 위 명령은 외부 패키지·API·실제 DB 없이 실행됩니다. `--demo`는 합성 음식200g의 160kcal·나트륨60mg 계산입니다. 실제 영양 평가나 전체 RAG 실행은 아닙니다. 전체 RAG에는 아래 설치·데이터·API 설정이 별도로 필요합니다.

```bash
python scripts/package_submission.py --output tmp/submission_three_files
```

정확히 세 파일만 담은 폴더와 ZIP을 만듭니다. 전체 공개 소스 묶음은 `python scripts/package_release.py --output tmp/public_source`로 별도 생성합니다. [제출 안내](docs/SUBMISSION.md)를 참고하세요.

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
python scripts/build_standalone.py --check
python -m unittest discover -s tests -v
python scripts/make_demo.py
RAG_DATA_DIR=data/demo RAG_CACHE_DIR=data/demo/index python src/capstone_compare.py calculate --request examples/demo.json
```

전체 자료 없는 공개 clone은 53개 중50통과·실데이터용3개 skip입니다. 가상 DB에는 실제 영양소 기준이 없습니다. 개별 보조 모듈을 수정했다면 `python scripts/build_standalone.py`로 제출 진입점의 내장 소스를 갱신하세요. CI는 이 일치 여부와 세 파일의 격리 실행을 검사합니다.

## 비교와 재평가

개발12문항에서 Baseline source Recall@5는6/8, 주제 필터+계산·확인+인용 검사 조합은8/8이었습니다. 검색 점수는 답변 정확도가 아닙니다. 이후 새24문항에서14충족·5부분·5실패를 기록했고 원문 검증·제한된 개념 처리를 보완했습니다. 모든 단계의 요약과 현재 남은 오류는 [평가 문서](results/evaluation.md)에 있습니다.

```bash
python src/capstone_compare.py evaluate --questions examples/evaluation_questions.jsonl --output results/runs/my_baseline
python src/capstone_compare.py compare --baseline results/runs/my_baseline --output results/comparisons/my_ablation
python scripts/evaluate_holdout.py --questions examples/holdout_questions_24.jsonl --plan examples/submission_review_plan.json --output results/holdout/my_review
```

7개 단독 방법은 hybrid, mmr, rerank, topic_filter, compression, guard, citations입니다. 전체 데이터·API가 필요하고 기존 결과를 덮어쓰지 않습니다. 정답 출처를 모델에 넣지 않으며 답변 내용 검토는 자동 지표와 별도로 수행합니다.

## 범위와 한계

한 번에 한 음식/성분을 계산합니다. 동명 음식은 식품코드 선택, 카페인은 표시 함량·개수, 조건별 기준은 인적 조건이 필요합니다. RNI/EAR/AI 초과를 과다로 판정하지 않으며 미확보 성분을0으로 바꾸지 않습니다. 밀도 없는 부피/질량 환산, IU·비타민 A/E의 형태 불명 상한 비교, 여러 항목의 실제 하루 합산, 개인 진단·처방 변경은 지원하지 않습니다.

관계 검증은 제한된 문장 구조를 대상으로 하며 정상 입력도 보류할 수 있습니다. 이번 총량/개수 질문1개도 오계산을 차단했지만 기대 계산을 완료하지 못했습니다. 일반 설명의 근거 함의·적용 범위·불필요한 인용 문제도 남아 있습니다. OCR3개 출처, EFSA부록8개, 모든 표·그림 전수 검토는 미완료입니다. [공개 범위](docs/PUBLISHING.md)를 참고하세요.
