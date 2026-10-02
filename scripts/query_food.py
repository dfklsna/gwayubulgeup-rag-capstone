"""Offline food lookup and unit-safe arithmetic; this is not a RAG/health assessment."""
import argparse
import json
import re
import sqlite3
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

PREPARED = Path(__file__).resolve().parents[1] / 'data' / 'prepared'


def normalize_name(value):
    return re.sub(r'[\s_]+', '', unicodedata.normalize('NFKC', value)).casefold()


def lookup(name, database=PREPARED / 'foods.sqlite'):
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        return [json.loads(row[0]) for row in db.execute(
            'SELECT f.record_json FROM foods f JOIN aliases a USING(food_code) '
            'WHERE a.normalized_alias=? ORDER BY f.food_code', (normalize_name(name),))]


def scale_food(record, amount, unit):
    try:
        amount = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValueError('섭취량은 유한한 양수여야 합니다.') from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError('섭취량은 유한한 양수여야 합니다.')
    conversions = {'g': ('g', 1), 'kg': ('g', 1000), 'ml': ('ml', 1), 'l': ('ml', 1000)}
    if unit.lower() not in conversions:
        raise ValueError('지원 단위: g, kg, ml, l')
    base_unit, multiplier = conversions[unit.lower()]
    if base_unit != record['basis']['unit']:
        raise ValueError('질량(g)과 부피(ml)는 밀도 정보 없이 변환할 수 없습니다.')
    factor = amount * multiplier / Decimal(str(record['basis']['amount']))
    return {
        'food_code': record['food_code'], 'food_name': record['food_name'],
        'origin': record['origin'], 'provenance': record['provenance'],
        'consumed': {'amount': str(amount), 'unit': unit}, 'factor': str(factor),
        'nutrients': {key: None if value is None else str(Decimal(str(value)) * factor)
                      for key, value in record['nutrients'].items()},
        'assessment_status': 'calculated_not_assessed',
        'note': '선택한 DB 항목 기준 계산치. 실제 조리법과 차이가 있을 수 있으며 과다 섭취 판정은 수행하지 않음.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--name')
    group.add_argument('--food-code')
    parser.add_argument('--amount')
    parser.add_argument('--unit')
    args = parser.parse_args()
    if args.name:
        if args.amount or args.unit:
            parser.error('먼저 후보를 확인한 후 --food-code로 계산할 항목을 지정하세요.')
        result = [{'food_code': r['food_code'], 'food_name': r['food_name'],
                   'origin': r['origin'], 'basis': r['basis']} for r in lookup(args.name)]
    else:
        with sqlite3.connect(f'file:{PREPARED / "foods.sqlite"}?mode=ro', uri=True) as db:
            row = db.execute('SELECT record_json FROM foods WHERE food_code=?', (args.food_code,)).fetchone()
        if row is None:
            parser.error('식품코드를 찾을 수 없습니다.')
        result = json.loads(row[0])
        if bool(args.amount) != bool(args.unit):
            parser.error('--amount와 --unit은 함께 지정하세요.')
        if args.amount:
            try:
                result = scale_food(result, args.amount, args.unit)
            except ValueError as exc:
                parser.error(str(exc))
        definitions = json.loads((PREPARED / 'food_nutrient_definitions.json').read_text())
        result['nutrients'] = {d['source_header']: result['nutrients'][d['nutrient_id']]
                               for d in definitions}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
