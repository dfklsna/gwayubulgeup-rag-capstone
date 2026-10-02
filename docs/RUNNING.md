# 실행 구성과 재현 조건

구현 코드와 설계·평가 문서는 다음과 같습니다.

- `src/capstone_compare.py`: 직접 작성한 보조 모듈·설정을 내장한 실행 진입점
- `results/design.md`: 현재 설계·데이터·실행 조건·한계
- `results/evaluation.md`: 현재 검증과 단계별 개선·실패 이력

```bash
python scripts/build_standalone.py --check
python scripts/package_submission.py --output tmp/submission_three_files
```

출력 폴더와 ZIP에는 세 파일만 들어갑니다. 기존 출력은 덮어쓰지 않습니다. 세 파일을 같은 폴더에 놓아도 실행됩니다.

```bash
python src/capstone_compare.py --help
python src/capstone_compare.py --demo
python src/capstone_compare.py --requirements
```

세 명령은 표준 라이브러리만으로 동작합니다. `--demo`는 가상 데이터의 계산 검증이며 실제 영양소 기준을 포함하지 않습니다. 필요한 내부 모듈이 없으면 내장 소스를 해시 확인 후 임시 폴더에 복원하고 종료 시 정리합니다. 전체 저장소에서는 개별 모듈을 사용합니다.

전체 RAG는 출력된 requirements의 패키지, API 키, 코퍼스/DB, 인덱스가 별도로 필요합니다. 따라서 데이터까지 포함한 완전한 오프라인 RAG 배포는 아닙니다. `RAG_DATA_DIR`, `RAG_CACHE_DIR`로 자료 경로를 지정합니다. 형식은 [데이터 안내](../data/README.md), 상세 흐름은 [설계](../results/design.md)를 참고하세요.

GitHub의 전체 코드·테스트·질문·집계 묶음은 다음 명령으로 별도 생성합니다.

```bash
python scripts/package_release.py --output tmp/public_source
```

이 묶음은 허용 목록과 파일별 SHA-256 manifest를 사용합니다. 키·개인 로컬 경로의 알려진 패턴을 검사하며 원문·실제 DB·임베딩·실행 로그를 제외합니다. 최신 결과는 `results/coverage_summary.json`입니다. 과거 집계는 삭제하지 않고 개발 이력으로 보존했습니다. 내용 검토는 assistant 판단으로 전문가 검증이 아닙니다.
