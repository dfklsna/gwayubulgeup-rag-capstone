"""Refresh counts and readable inventory after any document corpus update."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE/'data/prepared'


def rows(name):
    return [json.loads(line) for line in (OUT/name).read_text().splitlines() if line.strip()]


def refresh():
    current, legacy, combined = (rows(name) for name in ('documents.jsonl', 'legacy_documents.jsonl', 'all_documents.jsonl'))
    assert len(combined) == len(current) + len(legacy)
    entities = rows('entities.jsonl')
    catalog = {'documents': {'file':'all_documents.jsonl', 'records':len(combined), 'current_records':len(current), 'historical_records':len(legacy)},
               'entities': {'file':'entities.jsonl', 'records':len(entities), 'health_core':sum(e['domain'] != 'easter_egg' for e in entities), 'easter_eggs':sum(e['domain'] == 'easter_egg' for e in entities)},
               'note':'문서 수·건강 항목 수·음식 레코드 수는 서로 다른 단위이며 합산하지 않음.'}
    if (OUT/'food_preprocessing_summary.json').exists():
        food = json.loads((OUT/'food_preprocessing_summary.json').read_text())
        catalog['foods'] = {'file':'food_records.jsonl', 'sqlite':'foods.sqlite', 'records':food['food_records']}
    if (OUT/'nutrient_reference_summary.json').exists():
        refs = json.loads((OUT/'nutrient_reference_summary.json').read_text())
        catalog['nutrient_references'] = {'file':'nutrient_reference_intakes.jsonl','sqlite':'nutrient_references.sqlite',
            'records':refs['reference_records'],'numeric_records':refs['status_counts']['numeric'],
            'inherited_records':refs['status_counts']['inherit'],'nutrient_or_form_count':refs['nutrient_or_form_count']}
    (OUT/'data_catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n')
    lines = [f'통합 문서 전체 목록 — {len(combined)}개', f'이번 수집 정제본 {len(current)}개 + 기존 정제본 {len(legacy)}개. 과거 버전·중복·제외 자료 포함.', '']
    for i, d in enumerate(combined, 1):
        lines += [f'{i:03d}. [{d["source_id"]}] {d["title"]}',
                  f'     문서 ID: {d["document_id"]}',
                  f'     기본 검색 후보: {"예" if d.get("preferred_for_baseline") else "아니오"}',
                  f'     상태: {d["quality_status"]}', f'     출처: {d.get("url", "")}', '']
    (OUT/'전체_문서목록.txt').write_text('\n'.join(lines))
    old_list = OUT/'전체_193개_문서목록.txt'
    if old_list.exists() and len(combined) != 193:
        history = OUT/'historical_catalogs'
        history.mkdir(exist_ok=True)
        old_list.replace(history/old_list.name)
    bundle = [d for d in current if d['source_id']=='KR_KDRI_2025' and d.get('archive_sha256')]
    if bundle:
        manifest = [{'document_id':d['document_id'], 'title':d['title'], 'pages':d['preprocessing']['pages'],
                     'empty_text_pages':d['preprocessing']['empty_text_pages'], 'raw_path':d['raw_path'],
                     'text_path':f'texts/{d["document_id"]}.txt'} for d in bundle]
        status = {'status':'prepared_and_integrated', 'documents':manifest, 'total_pdf_pages':sum(d['pages'] for d in manifest),
                  'validation':'See validation_report.json: all page numbers and nonwhitespace extracted characters verified.',
                  'limitations':['Original PDF charts are retained but not OCRed.', 'PDF tables retain layout spacing; complete structured intake rules have not been built.', 'Full books and summaries share text; passage deduplication remains part of retrieval preparation.']}
        if 'nutrient_references' in catalog:
            status['structured_references'] = catalog['nutrient_references']
            status['limitations'][1] = 'Summary tables are structured; some nutrient form/scope mappings are intentionally blocked. See nutrient_reference_summary.json.'
        (OUT/'kdri_preprocessing_report.json').write_text(json.dumps(status, ensure_ascii=False, indent=2)+'\n')
        note = f'''한국인 영양소 섭취기준 상세본 정제 완료
추가 정제: {len(bundle)}개 PDF / {status['total_pdf_pages']:,}쪽
통합 문서: {len(combined)}개 = 이번 수집 {len(current)}개 + 기존 자료 {len(legacy)}개
원본 PDF와 정제 TXT를 document_id, URL, 원본 해시, ZIP 해시로 연결.
빈 페이지를 포함한 실제 PDF 페이지 번호와 정제 전후 페이지별 문자 보존 검증.
책에 인쇄된 페이지 번호와 PDF 페이지 번호는 구별해야 함.
나트륨 기준표(무기질 PDF 122쪽, 책 80쪽) 및 정오표 시각 대조 완료.
전체 기준표의 숫자·대상·단위 연결을 검증한 구조화 기준 DB는 아직 구축하지 않음.
추가 자료도 데이터 정제·통합까지 진행. Baseline·임베딩·RAG 평가 미실시.
원본/정제본 위치: data/prepared/kdri_preprocessing_report.json 참조.
'''
        if 'nutrient_references' in catalog:
            note = note.replace('전체 기준표의 숫자·대상·단위 연결을 검증한 구조화 기준 DB는 아직 구축하지 않음.',
                f"요약표 19개의 연령·성별·임신·수유 조건 기준 DB 구축: {refs['reference_records']}개 레코드(미설정 포함). 일부 성분 형태·급원은 음식 자동 비교 보류. 검증 범위는 nutrient_reference_validation.json 참조.")
        (BASE/'results/kdri_preprocessing_report.txt').write_text(note)
        readme = OUT/'읽어주세요.txt'
        text = readme.read_text()
        for marker in ('\n[KDRI 상세본 추가 확보 — 2026-10-02]\n', '\n[KDRI 상세본 정제 완료]\n'):
            text = text.split(marker)[0]
        text = text.replace('기존 문서 193개와 건강 core 106개', f'통합 문서 {len(combined)}개와 건강 core 106개')
        readme.write_text(text.rstrip()+'\n\n[KDRI 상세본 정제 완료]\n'+note)
    if 'nutrient_references' in catalog:
        readme = OUT/'읽어주세요.txt'
        marker = '\n[영양소 기준표 구조화]\n'
        text = readme.read_text().split(marker)[0]
        readme.write_text(text.rstrip()+'\n'+marker+
            f"19개 요약표 구조화: {refs['reference_records']}개 기준 레코드(미설정 포함), {refs['nutrient_or_form_count']}개 성분·형태.\n"+
            '기준 파일: nutrient_reference_intakes.jsonl / nutrient_references.sqlite\n'+
            '적용 제한: nutrient_reference_policy.json 및 ../../results/nutrient_reference_report.txt 참조.\n'+
            '검증: nutrient_reference_validation.json. 현재 조건별 조회·산술 비교 도구까지이며 RAG 엔진·성능 평가는 미실시.\n')
    print(json.dumps(catalog, ensure_ascii=False))


if __name__ == '__main__':
    refresh()
