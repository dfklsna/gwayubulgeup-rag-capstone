"""Deterministic KDRI lookup and food contribution check; not a RAG answer engine."""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from query_food import scale_food

OUT=Path(__file__).resolve().parents[1]/'data/prepared'


def load_rules():
    with sqlite3.connect(f'file:{OUT / "nutrient_references.sqlite"}?mode=ro',uri=True) as db:
        return [json.loads(r[0]) for r in db.execute('SELECT record_json FROM reference_intakes')]


def age_matches(d,months):
    return (d['age_min_months'] is None or months>=d['age_min_months']) and (d['age_max_months_exclusive'] is None or months<d['age_max_months_exclusive'])


def reference_lookup(nutrient_id,age_months,sex,life_stage='general',trimester=None,rules=None):
    months=Decimal(str(age_months))
    if not months.is_finite() or months<0:raise ValueError('연령(개월)은 유한한 0 이상의 수여야 합니다.')
    if sex not in ('male','female'):raise ValueError('기준표의 성별 male/female을 지정해야 합니다.')
    if life_stage not in ('general','pregnancy','lactation'):raise ValueError('지원 생애 상태: general/pregnancy/lactation')
    if life_stage!='general' and (sex!='female' or months<144):
        raise ValueError('임신·수유 특수행 자동 조회는 여성 12세 이상으로 제한합니다. 그 외 조건은 원문 개별 검토가 필요합니다.')
    if trimester is not None and (life_stage!='pregnancy' or trimester not in (1,2,3)):
        raise ValueError('임신 분기는 pregnancy에서 1/2/3으로 지정하세요.')
    rules=load_rules() if rules is None else rules
    candidates=[r for r in rules if r['nutrient_id']==nutrient_id]
    if not candidates:raise ValueError('알 수 없는 영양소 ID: '+nutrient_id)
    results=[]
    for kind in sorted({r['reference_type'] for r in candidates}):
        subset=[r for r in candidates if r['reference_type']==kind]
        universal=[r for r in subset if r['demographic']['life_stage']=='all' and age_matches(r['demographic'],months)]
        if universal:
            results.extend(deepcopy(universal));continue
        base=[r for r in subset if r['demographic']['life_stage']=='general' and r['demographic']['sex'] in (sex,'both') and age_matches(r['demographic'],months)]
        selected=base
        if life_stage!='general':
            selected=[r for r in subset if r['demographic']['life_stage']==life_stage]
            if not selected:
                # Never silently substitute a general-population rule for an absent special rule.
                continue
            if any(r['demographic']['trimester'] for r in selected):
                applicable=[r for r in selected if r['demographic']['trimester']==trimester]
                if not applicable:
                    r=deepcopy(selected[0]);r.update(status='requires_trimester' if trimester is None else 'not_established_for_trimester',value=None,min_value=None,max_value=None)
                    results.append(r);continue
                selected=applicable
        assert len(selected)<=1,(nutrient_id,kind,life_stage)
        for original in selected:
            r=deepcopy(original)
            if r['value_mode'] in ('add_to_age_matched_female','inherit_age_matched_female'):
                if len(base)!=1 or base[0]['status']!='numeric' or base[0]['value'] is None:
                    r.update(status='missing_age_matched_baseline',value=None)
                else:
                    baseline=base[0]
                    increment=Decimal(str(r['value'] or 0))
                    r['original_special_value']=r['value']
                    r['value']=float(Decimal(str(baseline['value']))+increment)
                    r['resolved_from_reference_ids']=[baseline['reference_id'],original['reference_id']]
                    r['baseline_source']=baseline['source']
                    r.update(status='numeric',value_mode='resolved_total')
            results.append(r)
    return results


def food_contribution(food,amount,unit,age_months,sex,life_stage='general',trimester=None,daily_complete=False,daily_energy_kcal=None):
    scaled=scale_food(food,amount,unit)
    definitions=json.loads((OUT/'nutrient_reference_definitions.json').read_text())
    rules=load_rules();results=[]
    energy=None
    if daily_energy_kcal is not None:
        energy=Decimal(str(daily_energy_kcal))
        if not energy.is_finite() or energy<=0:raise ValueError('하루 에너지 섭취량은 유한한 양수여야 합니다.')
        food_energy=scaled['nutrients'].get('R')
        if food_energy is not None and energy<Decimal(food_energy):
            raise ValueError('하루 전체 에너지는 보고한 음식의 에너지보다 작을 수 없습니다.')
    for definition in definitions:
        key=definition['nutrient_id']
        refs=reference_lookup(key,age_months,sex,life_stage,trimester,rules)
        for r in refs:
            result={'nutrient_id':key,'nutrient_name':definition['name'],'reference_id':r['reference_id'],
                    'reference_type':r['reference_type'],'reference_status':r['status'],
                    'source':r['source'],'intake_scope':r['intake_scope'],'reference_unit':r['unit'],
                    'reference_value':r['value'],'reference_min':r['min_value'],'reference_max':r['max_value'],
                    'reference_comparator':r['comparator'],'status':'not_compared'}
            if r.get('resolved_from_reference_ids'):
                result['resolved_from_reference_ids']=r['resolved_from_reference_ids']
                result['baseline_source']=r['baseline_source']
            if r['status']!='numeric':result['status']=r['status']
            elif not r['auto_food_comparison'] or not definition['food_columns']:
                result['status']='requires_form_scope_or_additional_data'
                result['reason']=r.get('comparison_block_reason',definition.get('food_mapping_note','조건별 성분 데이터 필요'))
            else:
                values=[scaled['nutrients'].get(c) for c in definition['food_columns']]
                if any(v is None for v in values):
                    result['status']='food_nutrient_missing'
                else:
                    value=sum((Decimal(v)*Decimal(f) for v,f in zip(values,definition['food_factors'])),Decimal(0))
                    result.update(food_amount=str(value),food_unit=definition['unit'])
                    if r['unit']=='percent_energy':
                        if not daily_complete or energy is None:
                            result['status']='requires_complete_daily_intake_and_energy'
                            results.append(result);continue
                        kcal_per_g=9 if key in ('fat','saturated_fat','trans_fat') else 4
                        value=value*kcal_per_g/energy*100
                        result['percent_energy']=str(value)
                    boundary=r['value'] if r['value'] is not None else r['max_value']
                    if boundary is not None and Decimal(str(boundary))>0:
                        result['percent_of_reference']=str(value/Decimal(str(boundary))*100)
                    if r['reference_type'] in ('EAR','RNI','AI'):
                        result['status']='adequacy_reference_only_not_an_excess_limit'
                    elif r['reference_type']=='EER':
                        result['status']='population_energy_reference_only'
                    else:
                        upper=Decimal(str(boundary)) if boundary is not None else None
                        outside=value>=upper if r['comparator']=='lt' else value>upper
                        if r['comparator']=='inclusive_range' and value<Decimal(str(r['min_value'])):
                            result['status']='below_AMDR_range'
                        elif outside:
                            result['status']='above_'+r['reference_type']+'_for_reported_intake'
                        else:
                            result['status']='within_reference_for_reported_intake' if daily_complete else 'not_above_reference_for_this_food_daily_total_unknown'
            results.append(result)
    return {'food_code':food['food_code'],'food_name':food['food_name'],'food_origin':food['origin'],
            'consumed':scaled['consumed'],'profile':{'age_months':str(age_months),'sex':sex,'life_stage':life_stage,'trimester':trimester},
            'daily_complete':daily_complete,'daily_energy_kcal':str(energy) if energy else None,
            'scope':'Reference lookup and arithmetic only; a single food is not a full-day record. No clinical risk, diagnosis, or RAG evaluation.',
            'results':results}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--nutrient');g.add_argument('--food-code')
    a=p.add_mutually_exclusive_group(required=True);a.add_argument('--age-years');a.add_argument('--age-months')
    p.add_argument('--sex',choices=['male','female'],required=True)
    p.add_argument('--life-stage',choices=['general','pregnancy','lactation'],default='general')
    p.add_argument('--trimester',type=int);p.add_argument('--amount');p.add_argument('--unit')
    p.add_argument('--daily-complete',action='store_true',help='선택한 음식이 하루 전체 섭취 기록인 경우에만 지정')
    p.add_argument('--daily-energy-kcal')
    args=p.parse_args()
    try:
        months=Decimal(args.age_years)*12 if args.age_years is not None else Decimal(args.age_months)
        if args.nutrient:
            result=reference_lookup(args.nutrient,months,args.sex,args.life_stage,args.trimester)
        else:
            if args.amount is None or args.unit is None:p.error('음식 비교에는 --amount와 --unit이 필요합니다.')
            with sqlite3.connect(f'file:{OUT / "foods.sqlite"}?mode=ro',uri=True) as db:
                row=db.execute('SELECT record_json FROM foods WHERE food_code=?',(args.food_code,)).fetchone()
            if not row:p.error('식품코드를 찾을 수 없습니다.')
            result=food_contribution(json.loads(row[0]),args.amount,args.unit,months,args.sex,args.life_stage,args.trimester,args.daily_complete,args.daily_energy_kcal)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,ArithmeticError) as exc:p.error(str(exc))

if __name__=='__main__':main()
