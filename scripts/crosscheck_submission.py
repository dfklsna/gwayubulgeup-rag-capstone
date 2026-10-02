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

    def check(label, question, valid, **fields):
        values = dict(kind='nutrient', name='비타민 C', nutrient_id='vitamin_c',
                      amount=500, unit='mg', count=1, evidence=question, intent='reported')
        values.update(fields)
        result = b.validate_extraction(question, b.ExtractedRequest(items=[b.ExtractedIntake(**values)]))
        assert bool(result.items) == valid, label
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
