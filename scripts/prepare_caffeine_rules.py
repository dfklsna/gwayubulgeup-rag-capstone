"""Build small, source-linked caffeine rules from the already collected MFDS document."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/prepared'


def main():
    docs = [json.loads(line) for line in (DATA/'documents.jsonl').open()]
    doc = next(d for d in docs if d['source_id']=='KR_CAFFEINE')
    for expected in ('성인 400㎎ 이하', '임산부 300㎎ 이하', '체중1kg당 2.5㎎ 이하'):
        if expected not in doc['text']:
            raise ValueError('카페인 원문이 바뀌었습니다. 규칙을 재검토하세요.')
    source = {k:doc[k] for k in ('document_id','source_id','title','url','raw_sha256')}
    rules = {}
    for group,value,unit in [('adult',400,'mg/day'),('pregnancy',300,'mg/day'),('child_or_teen',2.5,'mg/kg/day')]:
        rules[group] = {'value':value,'unit':unit,'reference_type':'maximum_daily_recommendation',
            'source':dict(source), 'note':'KDRI UL과 구분. 숫자로 성인/소아 경계를 추정하지 않고 사용자에게 해당 범주를 받음.'}
    rules['child_or_teen']['source']['supporting_url'] = 'https://impfood.mfds.go.kr/CFBCC02F02/getCntntsDetail?cntntsMngId=00005&cntntsSn=278410'
    (DATA/'caffeine_rules.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2)+'\n')
    print('caffeine_rules.json: 3 conditional recommendations created')


if __name__=='__main__':main()
