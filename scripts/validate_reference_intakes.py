"""Independent extraction reconciliation and meaningful reference-resolution checks."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from query_reference_intakes import reference_lookup,food_contribution,load_rules

BASE=Path(__file__).resolve().parents[1];OUT=BASE/'data/prepared'
rules=load_rules();cells=[json.loads(l) for l in (OUT/'kdri_reference_cells.jsonl').read_text().splitlines()]
checks=[]
def check(name,value):checks.append({'check':name,'passed':bool(value)})
def get(key,kind,age=30,sex='male',stage='general',trimester=None):
    found=[r for r in reference_lookup(key,Decimal(str(age))*12,sex,stage,trimester,rules) if r['reference_type']==kind]
    assert len(found)==1,(key,kind,age,sex,stage)
    return found[0]

check('all_19_tables_and_4608_cells',len(cells)==4608 and len({(c['pdf_page'],c['table']) for c in cells})==19)
check('unique_rule_ids',len({r['reference_id'] for r in rules})==len(rules))
check('no_null_as_zero',all(r['value'] is None and r['max_value'] is None for r in rules if r['status']=='not_established_in_table'))
check('all_rules_have_source_page_and_hash',all(r['source']['pdf_page'] in range(11,22) and len(r['source']['raw_sha256'])==64 for r in rules))
# Reconcile all 418 general rows with Poppler, independent of pdfplumber coordinates.
s=(OUT/'texts/KR_KDRI_2025__5a5567abef16.txt').read_text();parts=re.split(r'\[PDF page (\d+)\]\n',s)
pages={int(parts[i]):parts[i+1] for i in range(1,len(parts),2)}
pattern=r'^\s*(?:(?:영아|유아|남자|여자)\s+)?(0-5|6-11|1-2|3-5|6-8|9-11|12-14|15-18|19-29|30-49|50-64|65-74|75\s*이상)\s*(?:\((?:개월|세)\))?\s+(.*)$'
reconciled=0;errors=[]
for pn in range(11,22):
    lines=[m for line in pages[pn].splitlines() if (m:=re.match(pattern,line))]
    selected=[c for c in cells if c['pdf_page']==pn];tables=sorted({c['table'] for c in selected})
    if len(lines)!=22*len(tables):errors.append([pn,'row_count']);continue
    for ti,table in enumerate(tables):
        for ri in range(1,23):
            raw=re.sub(r'2\)', '', lines[ti*22+ri-1][2])
            normalized=''.join(c['value_text'] for c in selected if c['table']==table and c['row']==ri)
            if re.sub(r'\s','',raw)!=re.sub(r'\s','',normalized):errors.append([pn,table,ri])
            reconciled+=1
check('418_general_rows_match_independent_Poppler_extraction',reconciled==418 and not errors)
# Fixed expectations read from PDF table cells and footnotes, not generated output.
check('sodium_AI_not_UL',get('sodium','AI')['value']==1500 and not any(r['reference_type']=='UL' for r in reference_lookup('sodium',360,'male',rules=rules)))
check('sodium_CDRR_age_boundaries',[(a,get('sodium','CDRR',a)['value']) for a in (5,6,64,65,74,75)]==[(5,1500),(6,1700),(64,2300),(65,1900),(74,1900),(75,1800)])
check('choline_sex_specific_UL',get('choline','UL')['value']==3000 and get('choline','UL',sex='female')['value']==2500)
check('copper_ug_not_mg',get('copper','UL')['unit']=='ug' and get('copper','UL')['value']==10000)
check('folate_DFE_not_folic_acid_UL',get('folate','RNI')['unit']=='ug_DFE' and get('folic_acid','UL')['unit']=='ug' and not get('folic_acid','UL')['auto_food_comparison'])
check('magnesium_non_food_UL',get('magnesium','UL')['intake_scope']=='non_food_sources' and not get('magnesium','UL')['auto_food_comparison'])
check('niacin_forms_split',get('nicotinic_acid','UL')['value']==35 and get('nicotinamide','UL')['value']==850)
check('vitamin_A_E_UL_food_comparison_blocked',not get('vitamin_a','UL')['auto_food_comparison'] and not get('vitamin_e','UL')['auto_food_comparison'])
check('pregnancy_energy_three_trimesters',[get('energy','EER',30,'female','pregnancy',t)['value'] for t in (1,2,3)]==[1900,2240,2350])
check('pregnancy_trimester_missing_not_guessed',get('energy','EER',30,'female','pregnancy')['status']=='requires_trimester')
check('pregnancy_protein_second_third_trimester',[get('protein','RNI',30,'female','pregnancy',t)['value'] for t in (2,3)]==[60,80])
check('pregnancy_protein_first_trimester_not_invented',get('protein','RNI',30,'female','pregnancy',1)['status']=='not_established_for_trimester')
check('pregnancy_sodium_AI_addition_CDRR_absolute',get('sodium','AI',30,'female','pregnancy')['value']==1500 and get('sodium','CDRR',30,'female','pregnancy')['value']==2300)
check('calcium_UL_inherits_age_matched_female',[get('calcium','UL',a,'female','pregnancy')['value'] for a in (19,30)]==[2500,2000])
check('pregnancy_iodine_UL_not_established',get('iodine','UL',30,'female','pregnancy')['status']=='not_established_in_table')
check('pregnancy_folate_adds_to_baseline',get('folate','RNI',30,'female','pregnancy')['value']==620)
check('lactation_choline_addition',get('choline','AI',30,'female','lactation')['value']==500)
check('infant_DHA_not_EPA_DHA',get('dha','AI',age=0)['value']==100 and not any(r['status']=='numeric' for r in reference_lookup('epa_dha',0,'male',rules=rules)))
check('pregnancy_DHA_is_component_not_added_twice',get('epa_dha','AI',30,'female','pregnancy')['value']==300 and get('dha','AI',30,'female','pregnancy')['value']==200 and get('dha','AI',30,'female','pregnancy')['component_of']=='epa_dha')
check('water_total_and_liquid_separate',get('water_total','AI')['value']==2500 and get('water_liquid','AI')['value']==1200)
check('sugar_guideline_not_UL',get('total_sugar','recommendation')['max_value']==20 and get('added_sugar','recommendation')['max_value']==10)
check('cholesterol_under19_no_adult_limit',not reference_lookup('cholesterol',18*12,'male',rules=rules))
check('strict_and_inclusive_bounds_preserved',get('saturated_fat','AMDR')['comparator']=='lt' and get('total_sugar','recommendation')['comparator']=='le' and get('carbohydrate','AMDR')['comparator']=='inclusive_range')
with sqlite3.connect(f'file:{OUT/"foods.sqlite"}?mode=ro',uri=True) as db:
    food=json.loads(db.execute('SELECT record_json FROM foods WHERE food_code=?',('D314-612380000-0001',)).fetchone()[0])
example=food_contribution(food,400,'g',360,'male')
def result(data,key,kind):return next(r for r in data['results'] if r['nutrient_id']==key and r['reference_type']==kind)
r=result(example,'sodium','CDRR')
check('jellyfish_400g_sodium_and_ratio',Decimal(r['food_amount'])==1356 and abs(Decimal(r['percent_of_reference'])-Decimal('58.95652173913'))<Decimal('0.00001'))
check('single_food_does_not_prove_daily_safety',r['status']=='not_above_reference_for_this_food_daily_total_unknown')
check('single_food_sugar_requires_daily_context',result(example,'total_sugar','recommendation')['status']=='requires_complete_daily_intake_and_energy')
check('missing_vitamin_D_not_zero',result(example,'vitamin_d','AI')['status']=='food_nutrient_missing')
synthetic=deepcopy(food);synthetic['nutrients']['AD']=1600;synthetic['nutrients']['DN']=1000;synthetic['nutrients']['T']=100;synthetic['nutrients']['R']=1000;synthetic['nutrients']['X']=50;synthetic['nutrients']['AM']=300
mock=food_contribution(synthetic,100,'g',360,'male',daily_complete=True,daily_energy_kcal=1000)
check('above_AI_not_excess_verdict',result(mock,'sodium','AI')['status']=='adequacy_reference_only_not_an_excess_limit')
check('food_magnesium_never_compared_to_nonfood_UL',result(mock,'magnesium','UL')['status']=='requires_form_scope_or_additional_data')
check('RNI_not_used_as_upper_limit',result(mock,'protein','RNI')['status']=='adequacy_reference_only_not_an_excess_limit')
check('sugar_equal_20_percent_allowed',result(mock,'total_sugar','recommendation')['status']=='within_reference_for_reported_intake')
check('cholesterol_equal_300_violates_strict_less_than',result(mock,'cholesterol','recommendation')['status']=='above_recommendation_for_reported_intake')
synthetic['nutrients']['AD']=2400
check('CDRR_exceedance_distinct_from_UL',result(food_contribution(synthetic,100,'g',360,'male'),'sodium','CDRR')['status']=='above_CDRR_for_reported_intake')
invalid=0
for args in [('sodium',-1,'male'),('sodium','NaN','male'),('sodium',360,'unknown'),('sodium',360,'male','pregnancy'),('sodium',360,'female','pregnancy',4)]:
    try:reference_lookup(*args,rules=rules)
    except ValueError:invalid+=1
check('invalid_profile_rejected',invalid==5)
report={'passed':all(c['passed'] for c in checks),'checks':checks,'general_rows_reconciled':reconciled,'reconciliation_errors':errors,
        'visual_review':'All summary pages 11–21 inspected for headers, units, footnotes and special rows; not a full clinical validation.',
        'reference_sha256':hashlib.sha256((OUT/'nutrient_reference_intakes.jsonl').read_bytes()).hexdigest(),
        'note':'Extraction, arithmetic and conditional lookup validation; no RAG performance evaluation.'}
(OUT/'nutrient_reference_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
(OUT/'food_reference_example_jellyfish_400g.json').write_text(json.dumps(example,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'checks':len(checks),'failed':[c['check'] for c in checks if not c['passed']]},ensure_ascii=False))
if not report['passed']:raise SystemExit(1)
