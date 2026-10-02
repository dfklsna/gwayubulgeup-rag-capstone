"""Prepare the local food workbook without changing document corpora or original cells."""
import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from query_food import normalize_name, lookup, scale_food

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'data' / 'prepared'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def column_number(column):
    value = 0
    for character in column:
        value = value * 26 + ord(character) - 64
    return value


def read_workbook(path):
    with zipfile.ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            tree = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(t.text or '' for t in item.findall('.//s:t', NS)) for item in tree]
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        sheets = workbook.findall('s:sheets/s:sheet', NS)
        assert len(sheets) == 1, 'Unexpected sheet count'
        sheet_name = sheets[0].get('name')
        props = workbook.find('s:workbookPr', NS)
        epoch_1904 = props is not None and props.get('date1904') in ('1', 'true')
        with archive.open('xl/worksheets/sheet1.xml') as stream:
            for _, element in ET.iterparse(stream, events=('end',)):
                if element.tag != '{' + NS['s'] + '}row':
                    continue
                values = {}
                for cell in element.findall('s:c', NS):
                    assert cell.find('s:f', NS) is None, 'Formula needs explicit evaluation'
                    column = re.sub(r'\d', '', cell.get('r'))
                    value = cell.findtext('s:v', default='', namespaces=NS)
                    if cell.get('t') == 's':
                        value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//s:t', NS))
                    values[column] = value
                yield sheet_name, epoch_1904, int(element.get('r')), values
                element.clear()


def normalize_date(raw, epoch_1904):
    if not raw:
        return None
    if re.fullmatch(r'\d+(\.0+)?', raw):
        epoch = date(1904, 1, 1) if epoch_1904 else date(1899, 12, 30)
        return (epoch + timedelta(days=int(Decimal(raw)))).isoformat()
    return date.fromisoformat(raw).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='원본 음식 DB XLSX 경로')
    args = parser.parse_args()
    before = {p.name: digest(p) for p in (OUT / 'documents.jsonl', OUT / 'all_documents.jsonl', OUT / 'entities.jsonl')}
    original_hash = digest(args.input)
    original_dir = OUT / 'food_originals'
    original_dir.mkdir(exist_ok=True)
    copied = original_dir / args.input.name
    if copied.exists() and digest(copied) != original_hash:
        raise ValueError('보관된 원본과 입력 파일이 다릅니다. 새 버전의 별도 이름을 지정하세요.')
    if not copied.exists():
        shutil.copy2(args.input, copied)
    rows = iter(read_workbook(copied))
    sheet, epoch, header_row, headers = next(rows)
    assert header_row == 1 and len(headers) == 160
    nutrient_columns = sorted([c for c in headers if 18 <= column_number(c) <= 151], key=column_number)
    assert len(nutrient_columns) == 134
    definitions = []
    for c in nutrient_columns:
        match = re.search(r'\(([^()]*)\)$', headers[c])
        assert match, headers[c]
        definitions.append({'nutrient_id': c, 'source_column': c, 'source_header': headers[c],
                            'name': headers[c][:match.start()].strip(), 'unit': match[1]})
    save('food_nutrient_definitions.json', definitions)
    database = OUT / 'foods.sqlite'
    temporary = OUT / 'foods.building.sqlite'
    if temporary.exists():
        temporary.unlink()
    db = sqlite3.connect(temporary)
    db.executescript('CREATE TABLE foods(food_code TEXT PRIMARY KEY, food_name TEXT NOT NULL, origin TEXT NOT NULL, basis_unit TEXT NOT NULL, record_json TEXT NOT NULL);'
                     'CREATE TABLE aliases(normalized_alias TEXT NOT NULL, food_code TEXT NOT NULL REFERENCES foods(food_code), alias TEXT NOT NULL, PRIMARY KEY(normalized_alias,food_code));'
                     'CREATE INDEX alias_lookup ON aliases(normalized_alias);')
    counts = {k: Counter() for k in ('basis', 'origin', 'category', 'source', 'method')}
    numeric = missing = zero = count = 0
    jellyfish = []
    with (OUT / 'food_records.jsonl').open('w') as records, (OUT / 'food_aliases.jsonl').open('w') as aliases_file:
        for sheet, epoch, row_number, raw in rows:
            if not raw.get('A'):
                assert not any(raw.values()), f'Missing food code at row {row_number}'
                continue
            count += 1
            basis = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(g|ml)', raw['Q'])
            assert basis, raw['Q']
            nutrients = {}
            for c in nutrient_columns:
                value = raw.get(c, '')
                if value == '':
                    nutrients[c] = None
                    missing += 1
                else:
                    number = Decimal(value)
                    assert number.is_finite() and number >= 0, (row_number, c, value)
                    nutrients[c] = float(number)
                    numeric += 1
                    zero += number == 0
            name = raw['B']
            aliases = [name]
            # Curated synonym only; preserve all four independent food records.
            if name in ('냉채_해파리', '해파리냉채'):
                aliases = ['냉채_해파리', '해파리냉채', '해파리 냉채']
            record = {
                'food_code': raw['A'], 'food_name': name, 'normalized_name': normalize_name(name),
                'aliases': aliases, 'origin': raw['F'], 'category': raw['H'],
                'basis': {'amount': float(basis[1]), 'unit': basis[2], 'raw': raw['Q']},
                'serving_reference_raw': raw.get('EX', ''), 'food_weight_raw': raw.get('EY', ''),
                'nutrients': nutrients,
                'metadata_raw': {headers[c]: raw.get(c, '') for c in headers if c not in nutrient_columns},
                'provenance': {'original_file': str(copied.relative_to(OUT)), 'sha256': original_hash,
                               'sheet': sheet, 'row': row_number, 'source_agency': raw['EW'],
                               'generation_method': raw['FB'], 'generated_date': normalize_date(raw['FC'], epoch),
                               'reference_date': normalize_date(raw['FD'], epoch)},
                'quality_flags': ['volume_basis_requires_density_for_gram_input'] if basis[2] == 'ml' else [],
            }
            encoded = json.dumps(record, ensure_ascii=False, separators=(',', ':'))
            records.write(encoded + '\n')
            db.execute('INSERT INTO foods VALUES(?,?,?,?,?)', (raw['A'], name, raw['F'], basis[2], encoded))
            seen_aliases = set()
            for alias in aliases:
                normalized = normalize_name(alias)
                if normalized in seen_aliases:
                    continue
                seen_aliases.add(normalized)
                db.execute('INSERT INTO aliases VALUES(?,?,?)', (normalized, raw['A'], alias))
                aliases_file.write(json.dumps({'alias': alias, 'normalized_alias': normalized, 'food_code': raw['A']}, ensure_ascii=False) + '\n')
            for key, value in [('basis', raw['Q']), ('origin', raw['F']), ('category', raw['H']), ('source', raw['EW']), ('method', raw['FB'])]:
                counts[key][value] += 1
            if '해파리' in name and '냉채' in name:
                jellyfish.append(record)
    db.commit()
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert db.execute('SELECT count(*) FROM foods').fetchone()[0] == count
    db.close()
    temporary.replace(database)
    assert count == 19617
    assert numeric == 321719 and missing == 2306959
    assert counts['basis'] == {'100g': 13877, '100ml': 5740}
    assert len(jellyfish) == len(lookup('해파리 냉채', database)) == 4
    selected = next(r for r in jellyfish if r['food_code'] == 'D314-612380000-0001')
    example = scale_food(selected, '400', 'g')
    for key, value in {'R':'244', 'T':'16.52', 'U':'3.72', 'W':'35.72', 'X':'30.4', 'AD':'1356'}.items():
        assert Decimal(example['nutrients'][key]) == Decimal(value)
    assert selected['nutrients']['AA'] == 0 and selected['nutrients']['AL'] is None
    assert example['nutrients']['AL'] is None
    assert scale_food(selected, '0.4', 'kg')['nutrients'] == example['nutrients']
    guard_checks = 0
    for record, amount, unit in [(next(r for r in jellyfish if r['basis']['unit'] == 'ml'), '400', 'g'),
                                  (selected, '-1', 'g'), (selected, 'NaN', 'g'), (selected, 'Infinity', 'g'), (selected, '1', '개')]:
        try:
            scale_food(record, amount, unit)
        except ValueError:
            guard_checks += 1
        else:
            raise AssertionError('Unsafe conversion accepted')
    assert guard_checks == 5
    assert digest(args.input) == digest(copied) == original_hash
    assert before == {name: digest(OUT / name) for name in before}
    save('food_example_jellyfish_400g.json', example)
    entities = {r['entity_id']: r for r in map(json.loads, (OUT / 'entities.jsonl').read_text().splitlines())}
    mapping = {'AE':'C001','AK':'C002','AL':'C003','AZ':'C004','BI':'C005','AJ':'C008','AW':'C009','AS':'C010','AR':'C011','AU':'C012',
               'Z':'C014','AB':'C015','DN':'C016','AA':'C017','DS':'C018','DM':'C019','DO':'C020','DR':'C021','DU':'C022','DP':'C023',
               'DQ':'C024','AC':'C025','AD':'C026','AV':'C028','T':'C029','W':'C030','U':'C031','AN':'C032','AM':'C033','Y':'C034','X':'C035','CV':'C036','S':'C037','EU':'C038'}
    save('food_nutrient_entity_map.json', {
        'purpose': '관련 근거 검색을 위한 주제 연결. 섭취기준 수치 또는 자동 비교 규칙이 아님.',
        'comparison_status': 'conditional_reference_lookup_available' if (OUT/'nutrient_references.sqlite').exists() else 'not_implemented',
        'structured_reference_file': 'nutrient_reference_intakes.jsonl' if (OUT/'nutrient_references.sqlite').exists() else None,
        'mappings': [{'nutrient_id': c, 'source_header': headers[c], 'entity_id': e, 'entity_name': entities[e]['item'],
                      'source_ids': [s['source_id'] for s in entities[e]['sources']]} for c, e in mapping.items()],
        'required_reference_fields': ['nutrient_form', 'reference_unit', 'reference_type', 'age', 'sex', 'pregnancy_lactation', 'intake_scope', 'time_window', 'source_id', 'source_location'],
        'comparison_guards': ['총당류와 첨가당/유리당은 서로 다른 범위다.', '권장섭취량 초과를 상한섭취량 초과로 해석하지 않는다.',
                              '식품 유래와 보충제 유래 적용 범위를 구분한다.', '비타민 A RAE/레티놀, 엽산 DFE/엽산 형태, 지방산 단위를 구분한다.',
                              '한 음식 섭취만으로 하루 전체 섭취 또는 건강 위해를 단정하지 않는다.', '결측은 0이 아니며 총량과 하위 성분을 중복 합산하지 않는다.']})
    summary = {'food_records': count, 'nutrient_columns': len(nutrient_columns), 'numeric_nutrient_cells': numeric,
               'missing_nutrient_cells': missing, 'zero_nutrient_cells': zero, 'counts': counts,
               'source_workbook': str(args.input), 'source_sha256': original_hash, 'sheet': sheet,
               'reference_date': selected['provenance']['reference_date'], 'jellyfish_candidates': len(jellyfish),
               'related_entity_mappings': len(mapping), 'unmapped_nutrient_columns': [c for c in nutrient_columns if c not in mapping],
               'status': 'data_preparation_only'}
    save('food_preprocessing_summary.json', summary)
    save('food_validation_report.json', {'status':'passed', 'checks': ['160 source columns / 134 nutrients', '19617 unique food codes', 'basis counts preserved',
         'all nutrient values finite nonnegative or null', 'original workbook hash unchanged', 'existing document/entity hashes unchanged', 'SQLite integrity and row count',
         'four jellyfish lookup candidates', '400g arithmetic verified for six nutrients', 'zero vs missing preserved', 'kg conversion equivalence', 'five invalid input/conversion guards'],
         'existing_corpus_sha256': before})
    document_counts = {name: sum(1 for line in (OUT/name).open() if line.strip()) for name in ('documents.jsonl', 'legacy_documents.jsonl', 'all_documents.jsonl')}
    save('data_catalog.json', {'documents': {'file':'all_documents.jsonl','records':document_counts['all_documents.jsonl'],'current_records':document_counts['documents.jsonl'],'historical_records':document_counts['legacy_documents.jsonl']},
         'entities': {'file':'entities.jsonl','records':108,'health_core':106,'easter_eggs':2},
         'foods': {'file':'food_records.jsonl','sqlite':'foods.sqlite','records':count,'meaning':'식품코드별 음식 영양성분 레코드'},
         'note':'문서 수·건강 항목 수·음식 레코드 수는 서로 다른 단위이며 합산하지 않음.'})
    report = f'''음식 DB 정제 및 보관 결과
음식 레코드: {count:,}개 / 영양성분 열: {len(nutrient_columns)}개
100g 기준: {counts['basis']['100g']:,}개 / 100ml 기준: {counts['basis']['100ml']:,}개
숫자 셀: {numeric:,}개 / 결측 셀: {missing:,}개 / 실제 0 셀: {zero:,}개
원본 SHA256: {original_hash}
해파리냉채 관련 후보: 4개. 출처·식품코드·기준 단위를 각각 보존.
선택 예시: D314-612380000-0001 / 냉채_해파리 / 외식(분석함량) / 100g 기준.
400g: 244kcal, 단백질 16.52g, 지방 3.72g, 탄수화물 35.72g, 당류 30.4g, 나트륨 1356mg.
이 값은 특정 DB 항목의 계산 예시이며 실제 조리법 일치나 과다 섭취 판정이 아님.
문서 {document_counts['all_documents.jsonl']}개와 건강 core 106개는 음식 레코드 수와 별개이며 음식 정제 단계에서 원본/문서 정제본을 변경하지 않음.

준비된 흐름: 음식명 후보 조회 → 식품코드 선택 → 섭취량 단위 검증 → 영양성분 산술 계산.
후속 구현: 공식 근거에서 조건별 기준표 검증 → 근거 검색 → 하루 섭취 맥락과 함께 비교·설명.
현재 청킹·임베딩·Baseline RAG·건강 판정·RAG 평가는 미실시.
누락값은 null로 보존. 100ml 기록을 100g으로 자동 수정하지 않음. 원본 출처·날짜·시트·행·식품중량 보존.
1인분/식품중량을 사용자가 실제 먹은 양으로 자동 간주하지 않음.
영양소 연결 파일은 검색용이며 임상 기준 수치가 아님. 총당류/첨가당, 영양소 형태와 기준 종류를 구별해야 함.

재실행: .venv/bin/python scripts/prepare_food_db.py
조회: .venv/bin/python scripts/query_food.py --name '해파리냉채'
계산: .venv/bin/python scripts/query_food.py --food-code D314-612380000-0001 --amount 400 --unit g
'''
    (BASE / 'results' / 'food_preprocessing_report.txt').write_text(report)
    readme = OUT / '읽어주세요.txt'
    marker = '\n[음식 DB 추가]\n'
    original_text = readme.read_text().split(marker)[0]
    readme.write_text(original_text.rstrip() + '\n' + marker + report + '\n주요 파일: food_records.jsonl, foods.sqlite, food_nutrient_definitions.json, food_nutrient_entity_map.json, food_originals/, food_validation_report.json\n')
    print(report)


if __name__ == '__main__':
    main()
