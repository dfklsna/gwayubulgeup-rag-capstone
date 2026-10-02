"""Normalize both historical audit folders and consolidate them with prepared data.

Offline; does not change old inputs, collect new material, chunk, or embed.
documents.jsonl remains the current-source corpus. all_documents.jsonl is the
combined catalog, with historical evidence explicitly marked as non-default.
"""
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

from prepare_corpus import PROJECT, clean_spacing, dump, dump_lines, html_content, read_jsonl

ROOT = PROJECT.parent
OUT = PROJECT/'data/prepared'
OLD = ROOT/'rag-candidate-audit-20260924'
EXP = ROOT/'gwayubulgeup-expansion-audit-20260924'
COLLECTION = ROOT/'collection_runs/20261002'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized(value):
    """Whitespace only; retain numeric types, nulls, field names and decision values."""
    if isinstance(value, str):
        return clean_spacing(value.lstrip('\ufeff'))
    if isinstance(value, list):
        return [normalized(v) for v in value]
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()}
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def kind_for(path):
    name = path.stem
    if 'candidates' in name:
        return 'candidate_assessment'
    if name == 'core_entities':
        return 'entity_metadata'
    if 'relationships' in name:
        return 'entity_relationship'
    if 'source_registry' in name:
        return 'source_registry'
    if name in {'report', 'CODEX_HANDOFF', 'codebook'}:
        return 'audit_documentation'
    if 'verification' in name or 'checksums' in name or 'manifest' in name:
        return 'audit_verification'
    if name in {'easter_eggs', 'medication_response_policy', 'audit_issues'}:
        return 'policy_or_scope'
    return 'audit_metadata'


def read_values(path):
    raw = path.read_bytes()
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    content = raw.decode(encoding)
    if path.suffix == '.jsonl':
        return [json.loads(s) for s in content.splitlines() if s.strip()]
    if path.suffix == '.json':
        value = json.loads(content)
        return value if isinstance(value, list) else [value]
    if path.suffix == '.csv':
        # Type only explicit JSON collections/boolean/null, never doses or IDs.
        values = []
        for row in csv.DictReader(io.StringIO(content)):
            for k, v in row.items():
                if v and (v.lstrip().startswith(('[', '{')) or v in {'true', 'false', 'null'}):
                    try:
                        row[k] = json.loads(v)
                    except json.JSONDecodeError:
                        pass
            values.append(row)
        return values
    return [{'text': content}]


def clean_page_excerpt(body, sid):
    # Cache is already plain text: keep all substantive lines, only exact UI labels.
    ui = {'Skip to main content', 'Search the NHS website', 'Search', 'Menu', 'Close menu',
          'Back', 'Back to', 'Browse', 'Home', 'Toggle navigation', 'Share this page'}
    lines = [s.strip() for s in body.lstrip('\ufeff').replace('\r\n', '\n').splitlines() if s.strip()]
    original_count = len(lines)
    title = lines[0].split(' | ')[0].removesuffix(' - NHS').removesuffix(' - GOV.UK') if lines else ''
    explicit_titles = {'NCCIH_ASH': 'Ashwagandha', 'NCCIH_CURCUMIN': 'Turmeric',
                       'NHS_ARB': 'Losartan', 'NHS_SULFONYLUREA': 'Gliclazide',
                       'KR_ACETAMINOPHEN': '기본정보', 'KR_CREATINE': '건강기능식품 검색',
                       'KR_ZOLPIDEM': '마약류 최면진정제 이렇게 사용하세요 !'}
    title = explicit_titles.get(sid, title)
    candidates = [i for i,s in enumerate(lines) if i and (s == title or s.startswith(title+' -'))]
    if sid == 'MHRA_DEPENDENCE':
        candidates = [i for i,s in enumerate(lines) if i and s.startswith('Improving Information Supplied with Gabapentinoids')]
    start = (candidates[-1] if sid in {'NICE_FASTING','ASC_COLD'} else candidates[0]) if candidates else 0
    lines = lines[start:]
    footer_markers = {'Support links', 'Privacy and Policies'}
    if sid == 'KR_ANTIHISTAMINE':
        footer_markers.add('이전글')
    if sid == 'KR_ZOLPIDEM':
        footer_markers.add('관련기사')
    end = next((i for i,s in enumerate(lines) if i > 5 and s in footer_markers), len(lines))
    lines = lines[:end]
    removed = [s.strip() for s in lines if s.strip() in ui]
    return clean_spacing('\n'.join(s for s in lines if s.strip() not in ui)), {
        'removed_UI_labels': removed, 'prefix_lines_removed': start,
        'suffix_lines_removed': original_count-start-end,
        'body_boundary_method': 'observed_heading_and_footer' if candidates else 'exact_UI_labels_only'}


def run():
    (OUT/'legacy_originals').mkdir(exist_ok=True)
    (OUT/'legacy_texts').mkdir(exist_ok=True)
    current = read_jsonl(OUT/'documents.jsonl')
    current_file_hash = sha((OUT/'documents.jsonl').read_bytes())
    collection_manifest = read_jsonl(COLLECTION/'collection_manifest.jsonl')
    current_by_raw = defaultdict(list)
    current_by_source = defaultdict(list)
    current_by_text = defaultdict(list)
    for doc in current:
        current_by_raw[doc['raw_sha256']].append(doc['document_id'])
        current_by_source[doc['source_id']].append(doc['document_id'])
        current_by_text[(doc['source_id'],doc['text_sha256'])].append(doc['document_id'])
    targets = {r['source_id']: r for r in read_jsonl(COLLECTION/'metadata/collection_targets.jsonl')}
    registry = {r['source_id']: r for r in read_jsonl(EXP/'source_registry_v2.jsonl')}
    rejected = json.loads((EXP/'audit_issues.json').read_text())['rejected_label_evidence']
    # Known source mappings from old filenames. Do not invent URLs for unknown files.
    file_sources = {'aspartame_kr': 'KR_ASPARTAME', 'elder_exercise_kr': 'KR_EXERCISE',
                    'nice_diet': 'NICE_DIET', 'kdri2025_summary': 'KR_KDRI_2025',
                    'cold_33': 'ASC_CWI', 'cold_34': 'ASC_IMMERSION'}
    files = sorted(p for directory in [OLD, EXP] for p in directory.rglob('*')
                   if p.is_file() and not any(x in p.parts for x in ['node_modules', '__pycache__']))
    input_hashes = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in files}
    nonzip_hashes = {h for p, h in input_hashes.items() if not p.endswith('.zip')}
    inventory, records, legacy_docs, doc_dedup = [], {}, [], {}
    old_origins_for_current = defaultdict(list)
    source_documents = {'historical_html', 'historical_pdf', 'historical_text_cache', 'historical_page_excerpt', 'historical_label_excerpt'}

    for path in files:
        rel = str(path.relative_to(ROOT))
        raw = path.read_bytes()
        digest = input_hashes[rel]
        item = {'input_path': rel, 'sha256': digest, 'bytes': len(raw),
                'snapshot_label': '2026-09-24 audit; exact capture time may be unknown'}
        if path.suffix in {'.py', '.mjs'}:
            item['disposition'] = 'tooling_not_dataset'
            inventory.append(item)
            continue
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                members = [{'name': i.filename, 'sha256': sha(archive.read(i))}
                           for i in archive.infolist() if not i.is_dir()]
            item.update(disposition='archive_members_already_present', members=members)
            if any(m['sha256'] not in nonzip_hashes for m in members):
                raise ValueError('Unique archive members require explicit processing: ' + rel)
            inventory.append(item)
            continue
        saved = OUT/'legacy_originals'/f'{digest}{path.suffix}'
        if not saved.exists():
            saved.write_bytes(raw)
        item['stored_original'] = str(saved.relative_to(OUT))
        sid = file_sources.get(path.stem)
        text, tables, details, record_kind, source_info = '', [], {}, None, {}
        if path.parent.name in {'label_evidence', 'page_evidence'}:
            data = json.loads(raw.decode('utf-8-sig'))
            sid = data['source_id']
            source_info = data
            if path.parent.name == 'label_evidence':
                blocks = []
                for section in data['sections']:
                    title = clean_spacing(section.get('title', ''))
                    body = clean_spacing(section.get('text', ''))
                    if body:
                        blocks.append(('## '+title+'\n\n' if title else '')+body)
                text = '\n\n'.join(blocks)
                details = {'section_count': len(data['sections']), 'warnings': ['cached_excerpt_not_full_SPL; original_table_structure_unavailable']}
                record_kind = 'historical_label_excerpt'
            else:
                text, cleanup = clean_page_excerpt(data.get('body', ''), sid)
                details = {**cleanup, 'warnings': ['plain_text_cache; table_structure_and_remaining_navigation_require_review']}
                record_kind = 'historical_page_excerpt'
        elif path.suffix == '.html':
            text, tables, details = html_content(raw, sid or path.stem)
            record_kind = 'historical_html'
        elif path.suffix == '.pdf':
            q = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True, check=True)
            text = clean_spacing(q.stdout)
            if len(re.sub(r'\s', '', text)) < 100:
                item.update(disposition='needs_ocr', source_id=sid)
                inventory.append(item)
                continue
            record_kind, details = 'historical_pdf', {'warnings': ['PDF_layout_not_semantically_validated']}
        elif path.name == 'kdri2025_summary.txt':
            text = clean_spacing(path.read_text(encoding='utf-8-sig'))
            record_kind = 'historical_text_cache'
            details = {'warnings': ['derived_from_kdri2025_summary.pdf; possible_redundancy']}
        elif path.suffix in {'.png', '.jpg'}:
            disposition = 'generated_preview_not_source_text' if ('preview' in path.name or path.name == 'kdri_p7.png') else 'needs_ocr'
            item.update(disposition=disposition, source_id=sid)
            inventory.append(item)
            continue
        else:
            family = kind_for(path)
            # Generated CSV transport payload duplicates the separately parsed CSV files.
            if path.name == 'csv_payloads.json':
                item['disposition'] = 'generated_transport_payload_preserved'
                inventory.append(item)
                continue
            value_list = read_values(path)
            ids = []
            for number, value in enumerate(value_list, 1):
                payload = normalized(value)
                ident = 'LEGACY_RECORD_'+sha(canonical([family, payload]))[:24]
                if ident not in records:
                    records[ident] = {'record_id': ident, 'record_type': family, 'payload': payload,
                                      'payload_sha256': sha(canonical(payload)), 'origins': [],
                                      'evidence_role': 'audit_metadata_not_primary_source', 'preferred_for_baseline': False}
                records[ident]['origins'].append({'input_path': rel, 'input_sha256': digest, 'row_number': number})
                ids.append(ident)
            item.update(disposition='normalized_structured_or_audit_records', record_ids=ids, input_rows=len(value_list))
            inventory.append(item)
            continue

        assert record_kind in source_documents
        if not text.strip():
            item.update(disposition='empty_cached_content', source_id=sid)
            inventory.append(item)
            continue
        if digest in current_by_raw:
            item.update(disposition='exact_raw_duplicate_of_current', source_id=sid,
                        duplicate_of_document_ids=current_by_raw[digest])
            for ident in current_by_raw[digest]:
                old_origins_for_current[ident].append(rel)
            inventory.append(item)
            continue
        key = (sid, sha(text.encode()))
        if key in doc_dedup:
            item.update(disposition='duplicate_legacy_document', document_id=doc_dedup[key], source_id=sid)
            inventory.append(item)
            continue
        doc_id = 'LEGACY__'+(sid or path.stem)+'__'+digest[:12]
        doc_dedup[key] = doc_id
        target = targets.get(sid, {})
        source = registry.get(sid, {})
        if sid in rejected:
            status, reason = 'rejected_evidence', rejected[sid]
        elif sid in current_by_source:
            status, reason = 'historical_same_source', 'New collection contains this source ID; preserve old version separately.'
        elif sid in targets:
            status, reason = 'historical_requires_review', 'Historical content available; current source still has an unresolved preparation issue.'
        else:
            status, reason = 'outside_current_core_source_scope', 'Not in the 124 source collection plan; do not promote review/excluded evidence.'
        url = source_info.get('url') or source.get('url') or target.get('url')
        doc = {'document_id': doc_id, 'source_id': sid, 'title': source_info.get('title') or source.get('title') or path.stem,
               'text': text, 'text_sha256': sha(text.encode()), 'characters': len(text),
               'url': url, 'organization': source.get('organization'), 'country': source.get('country'),
               'published_or_updated': source_info.get('effective_date') or source.get('published_or_updated'),
               'captured_at': None, 'snapshot_label': '2026-09-24 audit',
               'input_path': rel, 'raw_path': item['stored_original'], 'raw_sha256': digest,
               'raw_kind': path.suffix.lstrip('.'), 'origin': record_kind, 'collection_batch': 'legacy_20260924',
               'linked_entities': target.get('linked_entities', []),
               'linked_dosage_profile_ids': target.get('linked_dosage_profile_ids', []),
               'source_scope_notes': source.get('verification_note', ''),
               'observed_version': {'setid': source_info.get('setid'), 'effective_date': source_info.get('effective_date')},
               'tables': tables, 'preprocessing': details, 'quality_status': status,
               'preferred_for_baseline': False, 'nondefault_reason': reason,
               'duplicate_of_document_ids': current_by_text.get((sid, sha(text.encode())), []),
               'related_current_document_ids': current_by_source.get(sid, [])}
        legacy_docs.append(doc)
        (OUT/'legacy_texts'/f'{doc_id}.txt').write_text(text+'\n', encoding='utf-8')
        item.update(disposition='prepared_historical_document', source_id=sid, document_id=doc_id)
        inventory.append(item)

    # Canonical curated metadata remains distinct from historical versions and official text.
    canonical_inputs = {'entities.jsonl': EXP/'combined_core_candidates.jsonl',
                        'entity_relationships.jsonl': EXP/'entity_relationships_v2.jsonl',
                        'source_registry.jsonl': EXP/'source_registry_v2.jsonl'}
    for filename, path in canonical_inputs.items():
        dump_lines(OUT/filename, [normalized(r) for r in read_jsonl(path)])
    for filename in ['easter_eggs.json', 'audit_issues.json']:
        dump(OUT/filename, normalized(json.loads((EXP/filename).read_text())))
    dump_lines(OUT/'legacy_documents.jsonl', legacy_docs)
    dump_lines(OUT/'legacy_records.jsonl', list(records.values()))
    dump_lines(OUT/'legacy_file_manifest.jsonl', inventory)
    dump(OUT/'legacy_input_hashes.json', input_hashes)
    combined = [{**d, 'collection_batch': '20261002', 'preferred_for_baseline': True,
                 'historical_exact_duplicate_paths': old_origins_for_current.get(d['document_id'], [])} for d in current]+legacy_docs
    dump_lines(OUT/'all_documents.jsonl', combined)
    entities = read_jsonl(OUT/'entities.jsonl')
    summary = {'stage': 'data_preparation_only', 'legacy_input_files': len(files),
               'legacy_input_rows_before_dedup': sum(i.get('input_rows', 0) for i in inventory),
               'legacy_normalized_records': len(records), 'record_types': dict(Counter(r['record_type'] for r in records.values())),
               'legacy_prepared_documents': len(legacy_docs), 'current_prepared_documents': len(current),
               'combined_documents': len(combined), 'legacy_document_statuses': dict(Counter(d['quality_status'] for d in legacy_docs)),
               'file_dispositions': dict(Counter(i['disposition'] for i in inventory)),
               'canonical_entities': len(entities),
               'canonical_health_core_entities': sum(e['domain'] != 'easter_egg' and e['dataset_decision']=='include' for e in entities),
               'canonical_relationships': len(read_jsonl(OUT/'entity_relationships.jsonl')),
               'canonical_sources': len(read_jsonl(OUT/'source_registry.jsonl')),
               'current_documents_sha256_before': current_file_hash,
               'all_documents_sha256': sha((OUT/'all_documents.jsonl').read_bytes()),
               'chunking_done': False, 'embedding_done': False, 'baseline_implemented': False}
    dump(OUT/'legacy_preprocessing_summary.json', summary)
    validate(files, input_hashes, current_file_hash, combined, inventory, records, rejected)
    report = f'''기존 자료 정제 및 통합 보관 결과

보관 위치: rag_capstone/data/prepared/
대상: rag-candidate-audit-20260924 및 gwayubulgeup-expansion-audit-20260924

기존 파일 {len(files)}개 조사. 코드·ZIP 중복·미리보기·OCR 대기까지 모든 파일의 처리 상태 기록.
기존 원문/발췌문 정제: {len(legacy_docs)}개 문서
이번 수집 정제본: {len(current)}개 문서
통합 문서 목록: {len(combined)}개 문서
기존 구조화 자료: 중복 제거 후 {len(records)}개 레코드 (항목 수가 아님)
기준 항목 목록: {len(entities)}개 = 건강 core 106 + 이스터에그 2
기준 관계: {summary['canonical_relationships']}개 / 전체 출처 등록부: {summary['canonical_sources']}개

주요 파일
- all_documents.jsonl: 이번 수집 문서 + 기존 정제 문서 통합 목록.
- documents.jsonl: 이번에 수집한 공식 자료의 정제본 {len(current)}개. 이 통합 단계에서 내용 변경 없음.
- legacy_documents.jsonl, legacy_texts/: 기존 원문·검증용 발췌문 정제본.
- legacy_records.jsonl: 후보 판단·수치 예시·관계·출처·정책·감사 기록을 정규화한 자료.
- entities.jsonl, entity_relationships.jsonl, source_registry.jsonl: 기존 최종 기준 목록.
- legacy_originals/: 코드와 중복 ZIP을 제외한 기존 자료를 해시 기준으로 중복 없이 보관.
- legacy_file_manifest.jsonl: 원래 파일 경로, 해시, 정제 결과, 제외·중복·OCR 상태.

사용 기준
- all_documents.jsonl에서 preferred_for_baseline=true인 문서가 현재 기본 검색 후보.
- 과거 문서는 보관하되 새 원문과 섞여 중복 검색되지 않도록 기본 후보에서 제외.
- 기존 후보 판단·숫자 예시는 감사 결과이며 공식 원문과 같은 권위로 취급하지 않음.
- 기존 review/exclude 상태와 이스터에그의 건강 검색 제외 원칙을 유지.
- DM_GABAPENTIN 구본 및 DM_LIDOCAINE 상충 라벨은 rejected_evidence로 보관.
- 기존 파일에 정확한 수집시각이 없으면 새 날짜를 부여하지 않고 알 수 없음으로 유지.
- 표 구조가 없는 기존 발췌문은 복원했다고 간주하지 않음.
- 과거 이미지/스캔과 해당 원문의 OCR은 미완료 상태를 유지.

재실행
  .venv/bin/python scripts/prepare_corpus.py
  .venv/bin/python scripts/validate_prepared.py
  .venv/bin/python scripts/prepare_legacy.py
첫 두 명령으로 이번 수집 자료를 재생성하면 마지막 명령으로 통합 목록도 갱신.
작업 범위는 정제·보관이며 청킹·임베딩·Baseline·평가 미실시.
'''
    (PROJECT/'results/legacy_preprocessing_report.txt').write_text(report, encoding='utf-8')
    readme = OUT/'읽어주세요.txt'
    suffix = ''
    if readme.exists() and '\n[음식 DB 추가]\n' in readme.read_text():
        suffix = '\n[음식 DB 추가]\n' + readme.read_text().split('\n[음식 DB 추가]\n', 1)[1]
    readme.write_text(report + suffix, encoding='utf-8')
    from refresh_prepared_catalog import refresh
    refresh()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def validate(files, before, current_hash, combined, inventory, records, rejected):
    checks = {
        'all_old_files_unchanged': all(sha(p.read_bytes()) == before[str(p.relative_to(ROOT))] for p in files),
        'current_corpus_unchanged': sha((OUT/'documents.jsonl').read_bytes()) == current_hash,
        'every_input_has_a_disposition': Counter(before.keys()) == Counter(i['input_path'] for i in inventory),
        'stored_copies_match_hashes': all(sha((OUT/i['stored_original']).read_bytes()) == i['sha256'] for i in inventory if 'stored_original' in i),
        'unique_combined_document_ids': len({d['document_id'] for d in combined}) == len(combined),
        'combined_text_hashes_match': all(sha(d['text'].encode()) == d['text_sha256'] for d in combined),
        'rejected_evidence_not_default': all(not d['preferred_for_baseline'] and d['quality_status']=='rejected_evidence' for d in combined if d['source_id'] in rejected),
        'both_rejected_labels_preserved': {d['source_id'] for d in combined if d['quality_status']=='rejected_evidence'} == set(rejected),
        'historical_evidence_not_silently_promoted': all(not d['preferred_for_baseline'] for d in combined if d['collection_batch']=='legacy_20260924'),
        'structured_records_have_traceable_origins': all(r['origins'] and all(o['input_path'] in before for o in r['origins']) for r in records.values()),
        'metadata_payload_hashes_match': all(sha(canonical(r['payload']))==r['payload_sha256'] for r in records.values()),
        'core_entity_count_unchanged': sum(e['domain']!='easter_egg' and e['dataset_decision']=='include' for e in read_jsonl(OUT/'entities.jsonl'))==106,
        'relationships_preserved': len(read_jsonl(OUT/'entity_relationships.jsonl'))==136,
    }
    dump(OUT/'legacy_validation_report.json', {'passed': all(checks.values()), 'checks': checks})
    if not all(checks.values()):
        raise ValueError('Validation failed: ' + str([k for k,v in checks.items() if not v]))


if __name__ == '__main__':
    run()
