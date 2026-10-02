"""Run pre-frozen new questions through the unchanged final pipeline, from natural language."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import capstone_compare as b
import experiments as e


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numeric_checks(result,expected):
    if not expected:return []
    items=result.get('calculation',{}).get('items',[])
    first=items[0] if items else {}
    rows=[]
    def check(name,actual,want,numeric=True):
        try:passed=(Decimal(str(actual))==Decimal(str(want))) if numeric else actual==want
        except Exception:passed=False
        rows.append({'check':name,'expected':want,'actual':actual,'passed':passed})
    for key,name in [('energy_kcal','에너지'),('sodium_mg','나트륨')]:
        if key in expected:check(key,first.get('nutrients',{}).get(name,{}).get('amount'),expected[key])
    if 'reported_amount' in expected:check('reported_amount',first.get('reported_amount'),expected['reported_amount'])
    refs=first.get('comparisons',[])
    if expected.get('reference_type'):
        chosen=[r for r in refs if r.get('reference_type')==expected['reference_type'] and ('sodium_mg' not in expected or r.get('nutrient_id')=='sodium')]
        row=chosen[0] if len(chosen)==1 else {}
        if 'reference_value' in expected:
            value=row.get('reference_value',row.get('value',row.get('reference_mg')))
            check('reference_value',value,expected['reference_value'])
        if 'reference_status' in expected:check('reference_status',row.get('status'),expected['reference_status'],False)
    for key,want in expected.get('salt_equivalent_mg',{}).items():
        conversions=result.get('calculation',{}).get('concept_calculation',{}).get('rows',[])
        matches=[r for r in conversions if r['kind']==key]
        check('salt_equivalent_'+key,matches[0]['output_amount_mg'] if len(matches)==1 else None,want)
    return rows


def run(questions,output,plan=None):
    questions=Path(questions);output=Path(output)
    plan=Path(plan) if plan else ROOT/'examples/holdout_plan.json'
    if output.exists():raise ValueError('기존 평가 폴더를 덮어쓰지 않습니다. 새 경로를 지정하세요.')
    cases=b.read_jsonl(questions)
    if len({c['id'] for c in cases})!=len(cases):raise ValueError('중복 질문 ID')
    selected=json.loads((ROOT/'examples/selected_strategy.json').read_text())['strategy']
    pipeline=e.Pipeline();strategy=e.Strategy(**selected)
    frozen_paths=[*sorted((ROOT/'src').glob('*.py')),ROOT/'src/knowledge_sources.json',ROOT/'scripts/query_food.py',ROOT/'scripts/query_reference_intakes.py',Path(__file__)]
    hashes={p.name:sha(p) for p in frozen_paths}
    output.mkdir(parents=True)
    manifest={'kind':'new_questions_end_to_end','created_at':datetime.now(timezone.utc).isoformat(),
              'questions_sha256':sha(questions),'plan_sha256':sha(plan),
              'code_sha256':hashes,'model':b.MODEL,'embedding_model':b.EMBED_MODEL,
              'corpus_sha256':pipeline.manifest['corpus_sha256'],'strategy':selected,
              'question_count':len(cases),'expected_source_cases':sum(bool(c['expected_source_ids']) for c in cases),
              'generation_review':'pending_assistant_review_not_expert_validation'}
    b.write_json(output/'run.json',manifest)
    (output/'frozen_questions.jsonl').write_bytes(questions.read_bytes())
    (output/'frozen_plan.json').write_bytes(plan.read_bytes())
    for path in frozen_paths:
        (output/path.name).write_bytes(path.read_bytes())
    def execute(case):
        start=time.perf_counter();stage='parse';req=None
        try:
            # Only the question goes to the model; gold criteria are never supplied.
            req=b.Request.model_validate(case['request']) if 'request' in case else b.parse_question(case['question'])
            stage='retrieve_calculate_generate'
            result=e.answer_variant(req,'combined',pipeline,strategy)
            result['execution_status']='completed'
        except Exception as exc:
            result={'execution_status':'error','error_type':type(exc).__name__,'http_status':getattr(exc,'status_code',None),
                    'failed_stage':stage,'request':req.model_dump() if req else None,'retrieved':[],
                    'answer':None,'calculation':{},'citation_check':{'unknown_ids':[]},'usage':None}
        expected=set(case['expected_source_ids']);found={h['source_id'] for h in result['retrieved']}
        result.update(case_id=case['id'],group=case.get('group',case.get('type','unknown')),question=case.get('question',case.get('request',{}).get('question')),
                      expected_source_ids=sorted(expected),source_recall_at_k=len(found & expected)/len(expected) if expected else None,
                      numeric_checks=numeric_checks(result,case.get('numeric_expectations',{})),
                      elapsed_including_parse_seconds=round(time.perf_counter()-start,3))
        b.write_json(output/(case['id']+'.json'),result)
        print(case['id'],result['execution_status'],flush=True)
        return result
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(execute,cases))
    if sha(questions)!=manifest['questions_sha256']:raise ValueError('평가 중 질문 파일이 바뀌었습니다.')
    for path in frozen_paths:
        if sha(path)!=hashes[path.name]:raise ValueError('평가 중 시스템 코드가 바뀌었습니다.')
    if sha(plan)!=manifest['plan_sha256']:raise ValueError('평가 중 계획 파일이 바뀌었습니다.')
    scored=[r['source_recall_at_k'] for r in results if r['source_recall_at_k'] is not None]
    checks=[check for r in results for check in r['numeric_checks']]
    summary={'cases':len(results),'completed':sum(r['execution_status']=='completed' for r in results),
             'errors':sum(r['execution_status']=='error' for r in results),
             'source_recall_at_k':sum(scored)/len(scored) if scored else None,'scored_retrieval_cases':len(scored),
             'numeric_checks_passed':sum(c['passed'] for c in checks),'numeric_checks_total':len(checks),
             'cases_with_unsupported_citation_ids':sum(bool(r['citation_check']['unknown_ids']) for r in results),
             'answer_quality':'pending_assistant_review_not_expert_validation',
             'no_pipeline_change_during_evaluation':True}
    b.write_json(output/'summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions',type=Path,default=ROOT/'examples/holdout_questions_24.jsonl')
    parser.add_argument('--plan',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.questions,args.output,args.plan),ensure_ascii=False,indent=2))
