# GitHub 공개 범위

공개 저장소는 [dfklsna/gwayubulgeup-rag-capstone](https://github.com/dfklsna/gwayubulgeup-rag-capstone)입니다. 코드·문서·합성 질문·테스트·출처 메타데이터·원문 없는 평가 집계를 게시합니다. 예제의 나이·성별·섭취량은 합성 시나리오입니다.

실제 `.env`, API 키, `.venv`, 제3자 원본·정제 본문, SQLite DB, 벡터 인덱스, 사용자 입력, 원시 검색 로그는 제외합니다. 코드 라이선스는 아직 지정하지 않았습니다. 출처별 데이터 재배포 조건은 별도 확인 대상입니다.

`scripts/package_release.py`는 허용 목록의 전체 공개 소스를 묶고 `PUBLIC_MANIFEST.json`에 해시를 남깁니다. `scripts/package_submission.py`는 필수 세 파일만 별도로 묶습니다. 내장 소스에는 직접 작성한 코드·설정과 출처 메타데이터만 포함하며 실제 데이터는 포함하지 않습니다.

현재 결과는 `results/coverage_summary.json`입니다. 이전 comparison/holdout/revision/release 집계는 개발 이력입니다. 점검 전 상세 문서는 `docs/history/`로 보존했습니다. 공개 환경에서67개 중64통과·실데이터용3skip과 세 파일 격리 실행을 검증했습니다. 게시 전 tracked diff·키 패턴·개인 경로·원문/DB 제외 여부를 확인합니다. 패턴 검사가 모든 비밀을 탐지하는 보안 인증은 아닙니다.
