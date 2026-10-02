# 제출과 실행에 필요한 파일

지정 제출물은 다음3개입니다.

- `src/capstone_compare.py`: 실행 진입점과 입력·계산 처리
- `results/design.md`: 설계, 데이터 준비 상태, 선택한 개선 구성과 한계
- `results/evaluation.md`: Baseline, 단독 개선7종, 새 질문·회귀 평가, 실패 및 제외한 실험

진입점은 보조 파일을 import하므로3개만 복사하면 실행되지 않습니다. 실행 가능한 소스 묶음에는 `src/experiments.py`, `src/knowledge_rules.py`, `src/knowledge_sources.json`, `scripts/`의 DB 조회 도구, requirements, 예제·테스트도 포함해야 합니다. 전체 실데이터 재현에는 별도 준비가 필요합니다.

```bash
python scripts/package_release.py --output tmp/submission_source
```

이 명령은 허용 목록의 코드·문서·합성 예제·집계를 폴더와 ZIP으로 묶고 파일별 SHA-256을 `PUBLIC_MANIFEST.json`에 기록합니다. `.env`, 키, 원문·정제 본문, 실제 DB·임베딩, 원시 실행 로그는 포함하지 않습니다. 공개 대상의 키 형식·개인 로컬 경로도 검사합니다. 이 검사는 알려지지 않은 모든 비밀 패턴을 보장하는 보안 인증은 아닙니다.

업로드 전 묶음에서 자동 테스트와 가상 예제를 실행합니다. 공개 저장소만 받은 사용자는 가상 예제와 코드 흐름을 재현할 수 있지만, 대용량 제3자 코퍼스를 곧바로 다운로드받는 구성은 아닙니다. 실제 데이터 준비 절차·재배포 범위는 `data/README.md`를 참고하세요.

최신 평가 집계는 `results/release_summary.json`입니다. 문서에 남은 이전 점수는 실험 이력이며 최신 서비스 성능과 혼동하지 않도록 구분했습니다. 내용 평가는 assistant 검토이며 전문가 검증이 아닙니다.
