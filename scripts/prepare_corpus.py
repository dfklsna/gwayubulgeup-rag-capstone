"""Offline corpus preparation only: no API, embedding, chunking, or evaluation.

Run: .venv/bin/python scripts/prepare_corpus.py
Inputs are immutable collection files; every artifact gets an inclusion decision.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from markdownify import markdownify

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_COLLECTION = PROJECT.parent / 'collection_runs' / '20261002'
NS = {'s': 'urn:hl7-org:v3'}


def read_jsonl(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def dump_lines(path, values):
    path.write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values), encoding='utf-8')


def clean_spacing(text):
    # Keep line structure, mathematical symbols, signs, ranges and units unchanged.
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\xa0', ' ')
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(x.rstrip() for x in text.splitlines())).strip()


def to_markdown(fragment):
    # Do not flatten 10^9 into 109, or chemical subscripts into adjacent digits.
    return markdownify(fragment, heading_style='ATX', strip=['a', 'img'],
                       sup_symbol='<sup>', sub_symbol='<sub>')


def table_records(root):
    tables = []
    for table in root.find_all('table'):
        if table.find_parent('table') is not None:
            continue
        rows = []
        for tr in table.find_all('tr'):
            if tr.find_parent('table') is not table:
                continue
            rows.append([{'text': cell.get_text(' ', strip=True), 'header': cell.name == 'th',
                          'rowspan': cell.get('rowspan', '1'), 'colspan': cell.get('colspan', '1')}
                         for cell in tr.find_all(['th', 'td'], recursive=False)])
        tables.append({'caption': table.caption.get_text(' ', strip=True) if table.caption else '',
                       'rows': rows, 'html': str(table)})
    return tables


def html_content(raw, sid):
    soup = BeautifulSoup(raw, 'lxml')
    selectors = []
    if sid.startswith('ODS_') or sid == 'NIH_SPORTS':
        selectors.append('#fact-sheet')
    if sid in {'EFSA_EGCG', 'EFSA_SUCRALOSE'}:
        selectors.append('#article__content .article__body')
    if sid == 'KR_EXERCISE':
        selectors.append('#print-content')
    if sid == 'NWS_COLDWATER':
        selectors.append('.cms-content')
    selectors += ['main', '[role="main"]', 'article', '#content', '#contents', '#main-content', 'body']
    selector, root = next((s, soup.select_one(s)) for s in selectors if soup.select_one(s) is not None)
    # Only known UI tags/classes. Do not drop hidden/collapsed scientific sections.
    for node in list(root.select('script,style,noscript,nav,footer,button,iframe,svg,'
                                 '[role="navigation"],.breadcrumb,.breadcrumbs,#onetrust-banner-sdk,.hover-content')):
        node.decompose()
    # Some public websites wrap the article in a form; retain those descendants.
    for node in list(root.select('form')):
        node.unwrap()
    tables = table_records(root)
    source_text = root.get_text(' ', strip=True)
    md = clean_spacing(to_markdown(str(root)))
    # Digit counts detect gross deletion, not number/unit alignment or clinical accuracy.
    before = Counter(re.findall(r'\d', source_text))
    after = Counter(re.findall(r'\d', md))
    lost = list((before - after).elements())
    warnings = []
    if selector == 'body':
        warnings.append('body_fallback_manual_review')
    if any(c['rowspan'] != '1' or c['colspan'] != '1' for t in tables for row in t['rows'] for c in row):
        warnings.append('merged_table_cells_preserved_in_table_records; review_markdown_alignment')
    if lost:
        warnings.append('numeric_token_conversion_mismatch')
    images = [{'src': image.get('src', ''), 'alt': image.get('alt', '')} for image in root.find_all('img')]
    if images:
        warnings.append('inline_image_content_not_OCRed; references_preserved')
    return md, tables, {'selector': selector, 'numeric_tokens_missing': lost,
                        'numeric_check_method': 'digit_multiset_only; not semantic number/unit validation',
                        'images': images, 'warnings': warnings}


def xml_content(raw, sid):
    root = ET.fromstring(raw)
    blocks, tables, sections = [], [], []
    if sid.startswith('DM_'):
        # Section narrative includes warnings, dosage, contraindications and tables.
        # Retain product elements as structured metadata, including strength attributes.
        for section in root.findall('.//s:section', NS):
            text = section.find('s:text', NS)
            if text is None:
                continue
            title = section.find('s:title', NS)
            title = ''.join(title.itertext()).strip() if title is not None else ''
            code = section.find('s:code', NS)
            code = dict(code.attrib) if code is not None else {}
            fragment = ET.tostring(text, encoding='unicode')
            fragment = re.sub(r'(<\/?)(?:ns\d+:)', r'\1', fragment)
            fragment = fragment.replace('<paragraph', '<p').replace('</paragraph>', '</p>')
            fragment = fragment.replace('<list', '<ul').replace('</list>', '</ul>')
            fragment = fragment.replace('<item', '<li').replace('</item>', '</li>')
            soup = BeautifulSoup(fragment, 'lxml')
            tables.extend(table_records(soup))
            # SPL content can carry scientific superscripts as styleCode attributes.
            for node in soup.select('[stylecode]'):
                if node.get('stylecode', '').lower() == 'superscript':
                    node.name = 'sup'
                elif node.get('stylecode', '').lower() == 'subscript':
                    node.name = 'sub'
            md = clean_spacing(to_markdown(str(soup)))
            if md:
                blocks.append(('## ' + title + '\n\n' if title else '') + md)
                sections.append({'title': title, 'code': code})
        products = []
        for product in root.findall('.//s:manufacturedProduct/s:manufacturedProduct', NS):
            products.append(ET.tostring(product, encoding='unicode'))
        return clean_spacing('\n\n'.join(blocks)), tables, {
            'parser': 'SPL_section_narratives', 'sections': sections,
            'product_elements_xml': products, 'warnings': ['product_attributes_in_metadata_not_narrative']}
    # MFDS DOC/ARTICLE titles are attributes: itertext alone would silently lose them.
    if root.tag == 'DOC':
        for article in root.findall('.//ARTICLE'):
            title = article.get('title', '')
            paragraphs = []
            for paragraph in article.findall('.//PARAGRAPH'):
                fragment = html.unescape(''.join(paragraph.itertext()))
                paragraphs.append(to_markdown(fragment))
            blocks.append(('## ' + title + '\n\n' if title else '') + '\n\n'.join(paragraphs))
        return clean_spacing('\n\n'.join(blocks)), [], {'parser': 'MFDS_DOC', 'document_title': root.get('title'), 'warnings': []}
    raise ValueError('No approved XML parser for ' + sid)


def choose(rows):
    """Choose one primary representation, keep distinct supporting PDFs/label parts."""
    sid = rows[0]['source_id']
    if any(r['status'] == 'needs_ocr' for r in rows):
        return [], 'source_main_content_requires_ocr'
    if sid.startswith('DM_'):
        return [r for r in rows if r['kind'] == 'xml'], 'prefer_official_SPL_over_duplicate_HTML'
    if sid == 'KR_ACETAMINOPHEN':
        return rows, 'keep_product_page_and_distinct_official_label_sections'
    pdfs = [r for r in rows if r['kind'] == 'pdf']
    primary_pdfs = [r for r in pdfs if r['role'] == 'document']
    if primary_pdfs:
        return pdfs, 'prefer_primary_document_PDF_over_landing_page'
    pages = [r for r in rows if r['kind'] == 'html']
    if pages:
        primary = max(pages, key=lambda r: r['extracted_characters'])
        return [primary] + pdfs, 'one_HTML_representation_plus_distinct_PDF_attachments'
    return pdfs, 'available_PDF'


def prepare(collection, output):
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_jsonl(collection / 'collection_manifest.jsonl')
    targets = {r['source_id']: r for r in read_jsonl(collection / 'metadata/collection_targets.jsonl')}
    grouped = defaultdict(list)
    for r in manifest:
        raw = (collection / r['raw_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != r['sha256']:
            raise ValueError('Input hash mismatch: ' + r['raw_path'])
        grouped[r['source_id']].append(r)
    documents, decisions, seen = [], [], {}
    for sid, rows in grouped.items():
        selected, selection_reason = choose(rows)
        for r in rows:
            decision = {'source_id': sid, 'raw_path': r['raw_path'], 'raw_sha256': r['sha256'],
                        'status': 'excluded', 'reason': selection_reason}
            if r not in selected:
                decisions.append(decision)
                continue
            raw = (collection / r['raw_path']).read_bytes()
            if r['kind'] == 'html':
                text, tables, details = html_content(raw, sid)
            elif r['kind'] == 'xml':
                text, tables, details = xml_content(raw, sid)
            else:
                # Keep PDF layout spaces and explicit page boundaries; don't collapse table columns.
                result = subprocess.run(['pdftotext', '-layout', str(collection / r['raw_path']), '-'],
                                        capture_output=True, text=True, check=True)
                pages = result.stdout.split('\f')
                # Poppler appends one separator after the last physical page.
                # Keep empty pages in the middle: filtering them shifts citations.
                if pages and not pages[-1].strip():
                    pages.pop()
                text = '\n\n'.join(f'[PDF page {i}]\n{clean_spacing(page)}' for i, page in enumerate(pages, 1))
                tables, details = [], {'parser': 'pdftotext_layout', 'pages': len(pages),
                                      'page_number_basis': 'physical_PDF_page_including_empty_pages',
                                      'empty_text_pages': [i for i, page in enumerate(pages, 1) if not page.strip()],
                                      'warnings': ['pdf_table_layout_manual_review']}
            if len(text.strip()) < 40:
                decision['reason'] = 'insufficient_cleaned_text'
                decisions.append(decision)
                continue
            sha = hashlib.sha256(text.encode()).hexdigest()
            # Deduplicate only identical content within a source; retain distinct official sources.
            key = (sid, sha)
            if key in seen:
                decision.update(reason='identical_cleaned_content', duplicate_of=seen[key])
                decisions.append(decision)
                continue
            doc_id = sid + '__' + r['sha256'][:12]
            seen[key] = doc_id
            target = targets[sid]
            doc = {'document_id': doc_id, 'source_id': sid, 'title': r.get('original_filename', r['registry_title']),
                   'text': text, 'text_sha256': sha, 'characters': len(text),
                   'url': r['url'], 'entry_url': target['url'], 'organization': target['organization'],
                   'country': target['source_record'].get('country'),
                   'published_or_updated': r['registry_published_or_updated'], 'captured_at': r['capture_at'],
                   'raw_path': r['raw_path'], 'raw_sha256': r['sha256'], 'raw_kind': r['kind'],
                   'origin': r['origin'], 'artifact_role': r['role'],
                   'linked_entities': target['linked_entities'],
                   'linked_dosage_profile_ids': target['linked_dosage_profile_ids'],
                   'source_scope_notes': r['source_scope_notes'], 'observed_version': r['observed_version'],
                   'tables': tables, 'preprocessing': details,
                   'quality_status': 'needs_review' if details.get('numeric_tokens_missing') or
                       'body_fallback_manual_review' in details['warnings'] else 'prepared_with_caveats'}
            if r.get('archive_sha256'):
                doc.update(original_filename=r['original_filename'], archive_sha256=r['archive_sha256'],
                           archive_raw_path=r['archive_raw_path'], source_scope_update=r.get('source_scope_update'),
                           overlap_note='Full books and summaries share introductory material; deduplicate relevant passages during retrieval preparation.')
            documents.append(doc)
            decision.update(status='included', document_id=doc_id, characters=len(text))
            decisions.append(decision)
    dump_lines(output / 'documents.jsonl', documents)
    (output / 'texts').mkdir(exist_ok=True)
    for doc in documents:
        (output/'texts'/f'{doc["document_id"]}.txt').write_text(doc['text']+'\n', encoding='utf-8')
    dump_lines(output / 'artifact_decisions.jsonl', decisions)
    covered_sources = {d['source_id'] for d in documents}
    entities = {e['entity_id'] for t in targets.values() for e in t['linked_entities']}
    covered_entities = {e['entity_id'] for d in documents for e in d['linked_entities']}
    summary = {'stage': 'data_preparation_only', 'chunking_done': False, 'embedding_done': False,
               'baseline_implemented': False, 'evaluation_done': False,
               'input_artifacts': len(manifest), 'input_sources': len(targets),
               'prepared_documents': len(documents), 'prepared_sources': len(covered_sources),
               'prepared_entity_count': len(covered_entities), 'entity_count': len(entities),
               'missing_entity_ids': sorted(entities-covered_entities),
               'excluded_source_ids': sorted(set(targets)-covered_sources),
               'characters': sum(d['characters'] for d in documents),
               'table_count': sum(len(d['tables']) for d in documents),
               'quality_status_counts': dict(Counter(d['quality_status'] for d in documents)),
               'numeric_conversion_warnings': [d['document_id'] for d in documents if d['preprocessing'].get('numeric_tokens_missing')],
               'body_fallback_sources': [d['source_id'] for d in documents if 'body_fallback_manual_review' in d['preprocessing']['warnings']],
               'source_coverage_note': 'Entity linkage does not prove that every question or dosage condition is supported.',
               'collection_manifest_sha256': hashlib.sha256((collection/'collection_manifest.jsonl').read_bytes()).hexdigest(),
               'corpus_sha256': hashlib.sha256((output/'documents.jsonl').read_bytes()).hexdigest()}
    dump(output / 'preprocessing_summary.json', summary)
    policy = collection / 'metadata/medication_response_policy.json'
    shutil.copyfile(policy, output / policy.name)
    # Preserve existing audited formulation/scope metadata separately from retrieval text.
    profiles = [r for r in read_jsonl(collection/'metadata/combined_core_candidates.jsonl')
                if r['domain'] == 'medication' and r['dataset_decision'] == 'include']
    dump_lines(output/'medication_scope_metadata.jsonl', profiles)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument('--output', type=Path, default=PROJECT/'data'/'prepared')
    args = parser.parse_args()
    prepare(args.collection, args.output)
