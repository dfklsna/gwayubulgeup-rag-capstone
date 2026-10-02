# GitHub 공개 준비

공개 저장소: [dfklsna/gwayubulgeup-rag-capstone](https://github.com/dfklsna/gwayubulgeup-rag-capstone). 코드·문서·합성 예제·평가 집계만 게시합니다.

공개 대상: `src/`, `scripts/`, `tests/`, `examples/`, README, requirements, `.env.example`, `.gitignore`, GitHub Actions, `results/design.md`, `results/evaluation.md`, 데이터 출처 메타데이터. examples의 나이·성별·섭취량은 가상 시나리오이며 사용자 개인정보가 아닙니다.

제외 대상: 실제 `.env`, API 키, `.venv`, 제3자 원본·정제 데이터, SQLite DB, 벡터 인덱스, 실제 사용자 섭취 기록, 로컬 실행 결과, 임시 파일. `.gitignore`는 이미 추적된 파일을 삭제하지 않으므로 게시 전에 `git ls-files`와 staged diff를 확인해야 합니다. 코드 라이선스는 아직 지정하지 않았습니다.

Baseline과 7개 단독 개선 및 최종 조합의 점수·실패 사례를 `results/evaluation.md`에 반영했습니다. 공개용 집계는 `results/comparison_summary.json`에 있습니다. 인증 실패나 미실행 항목을 성공으로 기재하지 않습니다. 생성 답변 인용문을 공개할 때도 출처별 재사용 조건을 확인합니다.

새 자연어 24문항의 합성 질문·평가 계획과 `results/holdout_summary.json`도 공개 대상으로 준비했습니다. `results/holdout/`의 원시 검색 본문·실행 기록은 제외합니다. 새로운 평가의 실패 사례도 평가 문서에 기록했습니다.

입력 오류 수정과 후속 실험의 공개 집계는 `results/revision_summary.json`입니다. 합성 질문 및 사전 평가 계획은 공개할 수 있지만 중간/최종 실행 폴더의 검색 원문은 계속 제외합니다. 최종 기본 구성에서 제외한 근거 검토 실험도 평가 문서에 이유를 기록했습니다. 공개 파일 복사본에서36개 테스트 중34개 통과·2개 skip과 오프라인 예제 계산을 확인했습니다.

제출 버전은 `scripts/package_release.py`의 허용 목록으로 묶습니다. 최신 공개 집계는 `results/release_summary.json`, 코드 근거 메타데이터는 `src/knowledge_sources.json`입니다. 본문은 포함하지 않습니다. 공개 복사본44개 테스트 중41개 통과·3개 skip과 오프라인 데모를 확인했고 ZIP 해시·제외 파일을 검사했습니다. 사용자가 승인한 공개 저장소 dfklsna/gwayubulgeup-rag-capstone을 사용합니다.
