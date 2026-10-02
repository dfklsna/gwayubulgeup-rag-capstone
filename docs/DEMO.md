# 실행 예시

프로젝트 루트에서 실행합니다. 인적 조건·섭취량은 합성 시나리오입니다. 전체 데이터가 없는 공개 clone은 아래 가상 예제부터 실행합니다.

## 세 파일만 받은 환경

```bash
python src/capstone_compare.py --help
python src/capstone_compare.py --demo
python src/capstone_compare.py --requirements
```

표준 라이브러리만 사용합니다. 세 파일을 한 폴더에 두었다면 `src/`를 빼세요. 가상 계산만 확인하며 전체 RAG에는 별도 패키지·데이터·키가 필요합니다.

## API 없이 실행하는 공개 예제

```bash
python scripts/make_demo.py
RAG_DATA_DIR=data/demo RAG_CACHE_DIR=data/demo/index python src/capstone_compare.py calculate --request examples/demo.json
python -m unittest discover -s tests -v
```

가상음식200g의 계산 흐름을 확인합니다. 가상 예제에는 실제 영양소 섭취기준이 없습니다. 전체 DB·인덱스를 요구하는 테스트는 skip됩니다.

## 전체 데이터를 준비한 뒤 실행하는 예시

데이터 준비는 [data/README.md](../data/README.md), API 설정은 프로젝트 README를 따릅니다. macOS에서는 `python scripts/configure_api_key.py`가 가려진 키 입력 창을 엽니다.

```bash
python src/capstone_compare.py ask --request examples/jellyfish_400g.json
python src/capstone_compare.py ask --request examples/caffeine_450mg.json
python src/capstone_compare.py ask --request examples/vitamin_c_2000mg.json
```

| 예시 | 코드 계산에서 확인한 핵심 결과 | 해석 범위 |
|---|---|---|
| 지정 코드의 해파리냉채400g | 244kcal, 나트륨1356mg | 조리법·출처가 다른 동명 음식과 구분. 하루 전체 안전 판정 아님 |
| 카페인150mg × 3잔, 일반 성인 | 450mg, 해당 권고400mg 초과 | 제품 표시 함량과 대상 조건을 입력한 사례 |
| 비타민 C1000mg × 2정, 지정 성인 조건 | 2000mg, 해당 UL2000mg을 넘지 않음 | 다른 급원 미확인, 개인별 안전 보장 아님 |

위 계산만 확인할 때는 `ask` 대신 `calculate`를 사용하면 API를 호출하지 않습니다. `ask`는 자연어 구조화·검색 등에서 API를 사용할 수 있습니다. 예시 결과는 이 저장소에 준비된 기준·데이터 버전을 전제로 합니다.

```bash
python src/capstone_compare.py ask --question '나트륨 1200mg과 소금 3g은 서로 어떻게 환산해?'
python src/capstone_compare.py ask --question '요구르트에 당류 12g이면 첨가당도 12g이야?'
python src/capstone_compare.py ask --question '칼슘 권장섭취량을 넘겼으면 UL도 넘은 거야?'
```

개념 설명은 검증된 문서 앵커가 있어야 동작합니다. 소금 환산은 근사량이며 실제 제품 조성 측정값이 아닙니다. 개념 원문이 없거나 변경되면 임의로 보충하지 않고 확인을 요청합니다.

## 확인 요청과 지원 밖 입력

- 음식명이 여러 DB 코드에 대응하면 코드·출처·단위를 제시하고 선택을 요청합니다.
- 커피 잔 수만으로 카페인 함량을 만들지 않습니다.
- 음수 섭취량, 밀도 없는 ml→g 환산, 형태가 필요한 비타민 단위는 확인 또는 보류 처리합니다.
- 현재 여러 음식·보충제의 실제 하루 합산은 지원하지 않습니다. “급원별 카페인을 함께 고려한다”는 개념 설명과 실제 다항목 계산은 구분합니다.
- 개인별 진단·처방 변경·법적 표시 의무 판단은 지원 범위 밖입니다.
