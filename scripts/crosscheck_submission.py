"""Cross-check source and isolated three-file validation with no API or real DB."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def probe(source):
    sys.path.insert(0, str(source))
    import capstone_compare as b
    rows = []

    def check(label, question, valid, profile=None, daily=False, expected_daily=False, **fields):
        values = dict(kind='nutrient', name='비타민 C', nutrient_id='vitamin_c',
                      amount=500, unit='mg', count=1, evidence=question, intent='reported')
        values.update(fields)
        result = b.validate_extraction(question, b.ExtractedRequest(profile=b.Profile(**(profile or {})), daily_complete=daily, items=[b.ExtractedIntake(**values)]))
        assert bool(result.items) == valid, label
        assert result.daily_complete == expected_daily, label
        if not valid:
            assert b.calculate(result)['status'] == 'needs_clarification', label
        rows.append({'case':label, 'accepted':bool(result.items), 'request':result.model_dump()})

    check('identity_wrong', '비타민 C 500mg 먹었어.', False, nutrient_id='vitamin_b6')
    check('identity_hidden_by_generic_name', '비타민 C 500mg 먹었어.', False, name='영양제', nutrient_id='vitamin_b6')
    check('identity_correct', '비타민 C 500mg 먹었어.', True)
    check('unknown_id', '비타민 C 500mg 먹었어.', False, nutrient_id='invented')
    check('both_ids_name_conflict', '비타민 C 500mg과 비타민 B6 500mg 먹었어.', False, nutrient_id='vitamin_b6')
    for count in (1,2):
        check(f'count_{count}', '비타민 C 500mg 2정 먹었어.', count==2, count=count)
        check(f'trailing_{count}', '비타민 C 한 정당 500mg짜리를 먹었어. 총 2정이야. 상한 기준과 비교해줘.', count==2, count=count)
        check(f'trailing_korean_{count}', '비타민 C 500mg 먹었어. 두 정이야.', count==2, count=count)
        check(f'total_{count}', '비타민 C 총 1000mg을 2정으로 먹었어.', count==1, amount=1000, count=count)
        check(f'other_medicine_{count}', '비타민 C 500mg 먹었어. 다른 약 2정도 먹었어.', False, count=count)
    for name in ('해파리냉채','이름모를음식'):
        check('omitted_'+name, f'파김치 150g과 {name} 400g 먹었어.', False,
              kind='food', name='파김치', nutrient_id=None, amount=400, unit='g')
    check('mineral_borrow', '비타민 C 500mg과 철 10mg 먹었어.', False, amount=10)
    check('weight_borrow', '체중 72kg이고 파김치 150g 먹었어.', False,
          kind='food', name='파김치', nutrient_id=None, amount=72, unit='kg')
    check('weight_correct', '체중 72kg이고 파김치 150g 먹었어.', True,
          kind='food', name='파김치', nutrient_id=None, amount=150, unit='g')
    for amount in (120,400):
        check(f'reference_{amount}', '카페인 120mg 먹었어. 일반 성인 400mg 기준으로 비교해줘.', amount==120,
              name='카페인', nutrient_id='caffeine', amount=amount)
    for order in ('비타민 D 25ug과 비타민 C 500mg','비타민 C 500mg과 비타민 D 25ug'):
        check('missing_nutrient_'+order, order+' 먹었어.', False)
    for order in ('파김치 150g과 식품코드 D314-612380000-0001 해파리냉채 400g',
                  '식품코드 D314-612380000-0001 해파리냉채 400g과 파김치 150g'):
        check('missing_food_'+order,order+' 먹었어.',False,kind='food',name='해파리냉채',
              food_code='D314-612380000-0001',nutrient_id=None,amount=400,unit='g')
    check('profile_reference_exempt','체중 70kg이고 비타민 C의 UL 2000mg인데 비타민 C 500mg 먹었어.',True)
    check('equal_amount_omission','비타민 B6 500mg과 비타민 C 500mg 먹었어.',False)
    for field,value in [('age_years',30),('sex','female'),('weight_kg',70),('life_stage','general'),('caffeine_group','adult'),('trimester',2)]:
        check('invented_'+field,'비타민 C 500mg 먹었어.',False,profile={field:value})
    check('profile_correct','30세 남성 일반 성인이고 체중은 70kg이야. 비타민 C 500mg 먹었어.',True,
          profile=dict(age_years=30,sex='male',life_stage='general',caffeine_group='adult',weight_kg=70))
    check('pregnancy_wrong','32세 여성이고 임신 중이야. 비타민 C 500mg 먹었어.',False,profile=dict(life_stage='general',caffeine_group='adult'))
    check('pregnancy_correct','32세 여성이고 임신 중이야. 비타민 C 500mg 먹었어.',True,profile=dict(life_stage='pregnancy'))
    check('lactation_reference','30세 여성이고 수유 중이야. 비타민 C 500mg 먹었어. 일반 성인 기준과 비교해줘.',False,profile=dict(caffeine_group='adult'))
    check('negated_pregnancy','임신·수유 중이 아닌 일반 성인이야. 비타민 C 500mg 먹었어.',True,profile=dict(life_stage='general'))
    for other in ['커피 두 잔','다른 약 2정','영양제 2정']:
        for count in [1,2]:
            for order in [f'비타민 C 500mg과 {other}',f'{other}과 비타민 C 500mg']:
                check(f'mixed_{order}_{count}',order+' 먹었어.',False,count=count)
    for verb in ['먹고 있어','복용 중이야','복용하고 있어','먹음','섭취하고 있어']:
        check('verb_correct_'+verb,'비타민 C 500mg '+verb+'.',True)
        for order in ['비타민 C 500mg과 비타민 D 25ug','비타민 D 25ug과 비타민 C 500mg']:
            check('verb_missing_'+order+verb,order+' '+verb+'.',False)
    check('evidence_partial','가정: 비타민 C 500mg 먹었어. 어떻게 돼?',False,evidence='비타민 C 500mg 먹었어.')
    check('evidence_full_hypothetical','가정: 비타민 C 500mg 먹었어. 어떻게 돼?',False)
    check('daily_invented','오늘 비타민 C 500mg 먹었어.',True,daily=True)
    check('daily_negated','비타민 C 500mg 먹었어. 오늘 먹은 전부가 아니야.',True,daily=True)
    check('daily_verified','비타민 C 500mg 먹었어. 오늘 하루 먹은 전부야.',True,daily=True,expected_daily=True)
    return rows


def run():
    with tempfile.TemporaryDirectory(prefix='capstone-crosscheck-') as folder:
        target = Path(folder)
        for name in ('src/capstone_compare.py','results/design.md','results/evaluation.md'):
            shutil.copy2(ROOT/name, target/Path(name).name)
        outputs=[]
        for source in (ROOT/'src', target):
            result = subprocess.run([sys.executable,'-I',str(Path(__file__).resolve()),
                                     '--probe',str(source)], cwd=target, text=True,
                                    capture_output=True, check=True)
            outputs.append(json.loads(result.stdout))
        assert outputs[0] == outputs[1], 'Source and embedded runtime disagree'
        # Python may create bytecode when imported, but no helpers may be copied beside the submission.
        assert sorted(p.name for p in target.iterdir() if p.is_file()) == ['capstone_compare.py','design.md','evaluation.md']
        return {'cases':len(outputs[0]), 'matching':len(outputs[0]),
                'expected_outcomes_passed':True, 'api_calls':0, 'real_db_required':False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    print(json.dumps(probe(args.probe) if args.probe else run(),ensure_ascii=False))
