# 데이터 준비 및 공개 범위

`source_manifest.json`은 수집 출처 139개의 메타데이터와 링크입니다. 실제 Baseline 검색 대상은 정제한 최신 문서 136개입니다. 출처 수와 문서 수는 다릅니다.

제3자 원문·정제 본문·음식 DB·임베딩을 저장소에 포함하지 않습니다. 웹 열람 가능 여부와 재배포 허용 여부는 별개이며, 출처별 이용조건 확인은 완료되지 않았습니다. 특히 수집한 식약처 카페인 페이지에는 무단 복제·이용에 관한 제한 문구가 있으므로 일괄 오픈 라이선스를 부여하지 않습니다. KDRI·논문·식품 DB에도 코드 라이선스를 적용하지 않습니다.

## 공개 저장소 실행

`python scripts/make_demo.py`로 직접 작성한 가상 데이터를 생성할 수 있습니다. 이 예제에는 실제 영양소 기준이 없으며 프로그램 설치·계산 흐름만 확인합니다. 실제 건강 분석용 데이터가 아닙니다.

## 전체 데이터 실행

자료 이용 권한을 확보한 뒤 로컬 `data/prepared/`에 다음 파일이 필요합니다.

- `documents.jsonl`: document_id, source_id, title, text, url. PDF 본문은 `[PDF page N]` 표식을 보존합니다.
- `foods.sqlite`: foods(food_code, food_name, origin, basis_unit, record_json), aliases(normalized_alias, food_code, alias).
- `food_nutrient_definitions.json`: nutrient_id, name, unit.
- `nutrient_references.sqlite`: reference_intakes 테이블의 record_json 열.
- `nutrient_reference_definitions.json`: 영양소 ID·단위·식품 성분 열 매핑.
- `caffeine_rules.json`: `python scripts/prepare_caffeine_rules.py`로 기존 KR_CAFFEINE 문서에서 생성.

음식 원본 XLSX 정제는 `python scripts/prepare_food_db.py --input /path/to/음식DB.xlsx`로 수행합니다. 추가 전처리 패키지는 [requirements-preprocessing.txt](../requirements-preprocessing.txt)에 있습니다. `python -m pip install -r requirements-preprocessing.txt`로 설치합니다. PDF 본문 추출은 별도 시스템 도구 Poppler의 `pdftotext`도 필요합니다. 음식 XLSX 정제는 기존 documents/all_documents/entities 등 수집·정제 파일이 준비된 디렉터리를 전제로 하며, 음식 파일 하나만으로 시작하는 명령은 아닙니다. 문서·KDRI·과거 자료 정제 스크립트는 기존 수집 디렉터리 구조를 전제로 하며, GitHub clone만으로 전체 수집 자료가 복원되지는 않습니다. 현재 단계에서 누구나 재현 가능한 실행 경로는 가상 데이터 예제입니다.

전체 데이터가 준비되면 `python src/capstone_compare.py prepare`, 이어서 `build`를 실행합니다. 새 자료를 사용하면 임베딩 인덱스를 다시 구축해야 합니다. 대용량 자료·로컬 요청·실행 로그는 `.gitignore`로 제외합니다.
