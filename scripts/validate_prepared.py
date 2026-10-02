"""Offline integrity and representative content checks; not RAG evaluation."""
from collections import Counter
import hashlib
import json
import re
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / 'data/prepared'
COLLECTION = PROJECT.parent / 'collection_runs/20261002'


def rows(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


docs = rows(DATA/'documents.jsonl')
manifest = rows(COLLECTION/'collection_manifest.jsonl')
decisions = rows(DATA/'artifact_decisions.jsonl')
summary = json.loads((DATA/'preprocessing_summary.json').read_text())
checks = []


def check(name, condition):
    checks.append({'check': name, 'passed': bool(condition)})


check('unique_document_ids', len({d['document_id'] for d in docs}) == len(docs))
check('all_collected_artifacts_have_a_decision',
      Counter(d['raw_path'] for d in decisions) == Counter(r['raw_path'] for r in manifest))
check('all_cleaned_text_hashes_match', all(hashlib.sha256(d['text'].encode()).hexdigest() == d['text_sha256'] for d in docs))
check('raw_collection_hashes_unchanged', all(hashlib.sha256((COLLECTION/r['raw_path']).read_bytes()).hexdigest() == r['sha256'] for r in manifest))
check('collection_manifest_unchanged', hashlib.sha256((COLLECTION/'collection_manifest.jsonl').read_bytes()).hexdigest() == summary['collection_manifest_sha256'])
check('collection_metadata_inputs_unchanged', all(
    hashlib.sha256((COLLECTION.parents[1]/name).read_bytes()).hexdigest() == sha
    for name, sha in json.loads((COLLECTION/'metadata/input_hashes.json').read_text()).items()))
check('no_empty_documents', all(len(d['text'].strip()) >= 40 for d in docs))
check('all_documents_have_provenance', all(d['source_id'] and d['url'] and d['raw_sha256'] and d['linked_entities'] for d in docs))
check('all_106_entity_links_retained', len({e['entity_id'] for d in docs for e in d['linked_entities']}) == 106)
check('OCR_documents_excluded', not ({d['source_id'] for d in docs} & {'ASC_CWI', 'ASC_IMMERSION', 'KR_ASPARTAME'}))
check('all_37_DailyMed_sources_use_XML', sum(d['source_id'].startswith('DM_') for d in docs) == 37 and
      all(d['raw_kind'] == 'xml' for d in docs if d['source_id'].startswith('DM_')))
check('all_DailyMed_product_attributes_retained', all(d['preprocessing'].get('product_elements_xml') for d in docs if d['source_id'].startswith('DM_')))
check('no_numeric_digit_loss_flag', not summary['numeric_conversion_warnings'])
check('no_body_fallback', not summary['body_fallback_sources'])
check('readable_text_exports_match', all((DATA/'texts'/f'{d["document_id"]}.txt').read_text() == d['text']+'\n' for d in docs))

def text(sid, role=None):
    return '\n'.join(d['text'] for d in docs if d['source_id'] == sid and (not role or d['artifact_role'] == role))

# These fixed evidence fragments exercise specific extraction failure modes.
# They are not evaluation questions, answers, or medical recommendations.
check('MFDS_article_attribute_title_retained', '## 1. 주효능·효과' in text('KR_ACETAMINOPHEN', 'label_EE'))
check('MFDS_unit_and_condition_fragment_retained', '4그램 (8정)' in text('KR_ACETAMINOPHEN', 'label_UD') and
      '만 12세 이상' in text('KR_ACETAMINOPHEN', 'label_UD'))
check('KDCA_article_inside_form_retained', '만성 질환이 있는데 운동을 해도 되는지' in text('KR_EXERCISE'))
check('ODS_reference_popup_removed', 'carrier protein [1,2]' in text('ODS_B5'))
check('ODS_unit_fragment_retained', '100 mcg (4,000 IU)' in text('ODS_D'))
check('scientific_superscripts_retained', any('<sup>' in d['text'] for d in docs))
check('scientific_subscripts_retained', any('<sub>' in d['text'] for d in docs))
check('NWS_navigation_removed', 'Cold Water Can Be Dangerous' in text('NWS_COLDWATER') and
      'Forecast Models' not in text('NWS_COLDWATER'))
check('merged_cells_have_original_table_HTML', all(t['html'].startswith('<table') for d in docs for t in d['tables']))

# Full KDRI books include empty physical pages. Test numbering and page-local
# content rather than merely finding numbers somewhere in a long document.
kdri_bundle = [d for d in docs if d.get('archive_sha256') and d['source_id'] == 'KR_KDRI_2025']
if kdri_bundle:
    expected = json.loads((COLLECTION/'metadata/kdri_full_bundle_download.json').read_text())['members']
    check('KDRI_all_six_bundle_PDFs_included', {d['raw_sha256'] for d in kdri_bundle} == {d['sha256'] for d in expected})
    page_count_ok = content_ok = True
    for d in kdri_bundle:
        info = subprocess.run(['pdfinfo', str(COLLECTION/d['raw_path'])], capture_output=True, text=True, check=True).stdout
        count = int(re.search(r'^Pages:\s+(\d+)', info, re.M)[1])
        raw_text = subprocess.run(['pdftotext', '-layout', str(COLLECTION/d['raw_path']), '-'], capture_output=True, text=True, check=True).stdout
        source_pages = raw_text.split('\f')
        if not source_pages[-1].strip():
            source_pages.pop()
        parts = re.split(r'^\[PDF page (\d+)\]\n', d['text'], flags=re.M)
        markers, texts = parts[1::2], parts[2::2]
        page_count_ok &= len(source_pages) == len(texts) == count == d['preprocessing']['pages'] and list(map(int, markers)) == list(range(1, count+1))
        content_ok &= all(re.sub(r'\s', '', original) == re.sub(r'\s', '', cleaned) for original, cleaned in zip(source_pages, texts))
    check('KDRI_physical_page_numbers_match_pdfinfo', page_count_ok)
    check('KDRI_every_page_preserves_all_nonwhitespace_characters', content_ok)
    check('KDRI_no_unicode_replacement_characters', all('\ufffd' not in d['text'] for d in kdri_bundle))

report = {'passed': all(c['passed'] for c in checks), 'checks': checks,
          'note': 'Data integrity and representative extraction checks only. No clinical validation or retrieval/answer evaluation.',
          'corpus_sha256': hashlib.sha256((DATA/'documents.jsonl').read_bytes()).hexdigest()}
(DATA/'validation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
result_dir = PROJECT/'results'
result_dir.mkdir(exist_ok=True)
merged = sum(any(c['rowspan'] != '1' or c['colspan'] != '1' for row in t['rows'] for c in row) for d in docs for t in d['tables'])
with_images = sum(bool(d['preprocessing'].get('images')) for d in docs)
body = f'''과유불급 RAG 데이터 1차 정제 결과

현재 단계: 데이터 정제만 수행. 청킹·문서 임베딩·Baseline 구현·RAG 평가는 미실시.

입력: {summary['input_sources']}개 출처 / {summary['input_artifacts']}개 수집 파일
정제본: {len(docs)}개 문서 / {summary['prepared_sources']}개 출처 / 106개 항목 연결
정제 텍스트: {summary['characters']:,}자 (참고문헌과 일부 문서 간 내용 중복 포함)
표: {summary['table_count']}개, 셀 병합이 있는 표 {merged}개
검증: {sum(c['passed'] for c in checks)}/{len(checks)}개 통과

수행한 작업
- 기존 수집 파일과 계획·감사 원본은 변경하지 않음.
- DailyMed 37개 출처는 공식 SPL XML을 사용하고 중복 HTML은 제외.
- NIH 본문에 반복 삽입된 참고문헌 팝업 제거, 참고문헌 본 목록은 유지.
- 메뉴·버튼·스크립트·스타일 제거. 본문을 감싸는 form은 내용 유지.
- 단락·제목·수치·단위 유지, 위첨자·아래첨자는 명시적 태그로 보존.
- 표는 본문 표현 외에 원 HTML 및 셀별 rowspan/colspan도 보존.
- PDF는 페이지 번호와 레이아웃 공백을 유지.
- 의약품의 국가, 연결 용법 profile, 원문 버전, 제품 구조 속성을 보존.
- 파일별 포함·제외 이유와 URL·원본 해시를 기록.

남은 처리 및 한계
- ASC_CWI, ASC_IMMERSION, KR_ASPARTAME: 주요 자료가 스캔/이미지여서 OCR 전 정제본 제외.
- 본문 이미지가 있는 {with_images}개 문서는 이미지 경로·대체텍스트를 기록했지만 이미지 내용은 OCR하지 않음.
- 병합 표 {merged}개 및 PDF {sum(d['raw_kind']=='pdf' for d in docs)}개는 청킹 전에 필요한 표의 행·열·단위 대응을 원문과 검토해야 함.
- 수치 검사는 숫자 문자 보존 검사이며 수치와 대상·단위의 의미적 일치를 보증하지 않음.
- 문서 전체가 임상적으로 검토된 상태가 아니며 106개 항목 연결이 모든 질문의 근거 확보를 뜻하지 않음.
- KDRI 상세본 묶음 PDF {len(kdri_bundle)}개 정제 포함. 미확보 추가 첨부는 collection_failures.jsonl 참조.
- 언어 번역·LLM 요약·추론으로 원문에 없는 문장을 추가하지 않음.

파일 안내
data/prepared/documents.jsonl: 후속 RAG 구현의 입력 후보. text와 출처·표·품질 metadata 포함.
data/prepared/texts/: 사람이 읽을 수 있는 문서별 TXT.
data/prepared/artifact_decisions.jsonl: {len(manifest)}개 파일의 포함·제외 이유.
data/prepared/preprocessing_summary.json: 집계와 현재 단계.
data/prepared/validation_report.json: 개별 검증 결과.
data/prepared/medication_scope_metadata.jsonl: 기존 의약품 40개 제형·조건 metadata.

재실행
프로젝트 폴더에서 다음 명령을 실행:
  .venv/bin/python scripts/prepare_corpus.py
  .venv/bin/python scripts/validate_prepared.py
새 환경: Python 3.12, requirements-preprocessing.txt, Poppler의 pdftotext 필요.

제출물 계획
src/capstone_compare.py: 다음 Baseline 구현 단계에서 작성.
results/design.md: 확정한 문제·자료 범위·Baseline 구조를 다음 단계에서 작성.
results/evaluation.md: 실제 Baseline 평가 후 기록. 현재 성능 수치는 없음.

사전 환경 점검 기록
초기에 OpenAI 임베딩 API에 짧은 연결 확인 문자열 1건으로 접근했으나 401 invalid_api_key 응답.
수집 문서를 API로 보내거나 임베딩한 적은 없음. 향후 API 실행 단계에서 환경변수 인증 확인 필요.
키 값은 파일·문서·로그에 기록하지 않음.
'''
(result_dir/'preprocessing_report.txt').write_text(body)
print(json.dumps({'passed': report['passed'], 'checks': len(checks), 'failed': [c['check'] for c in checks if not c['passed']]}, ensure_ascii=False))
if not report['passed']:
    raise SystemExit(1)
