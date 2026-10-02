"""Create fabricated, non-medical data for public-repository smoke tests. No external data."""
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/demo'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    docs=[{'document_id':'DEMO_ONLY','source_id':'SYNTHETIC','title':'가상 데이터 사용 안내',
        'url':None,'text':'이 문서는 프로그램 실행 확인용으로 직접 작성한 가상 자료입니다. 가상음식은 실제 음식이 아닙니다. 실제 영양 평가에 사용하지 마세요.'}]
    food={'food_code':'DEMO-001','food_name':'가상음식','origin':'synthetic',
        'basis':{'amount':100,'unit':'g'},'nutrients':{'R':80,'T':2,'AD':30,'EU':None},
        'provenance':{'sheet':'synthetic','row':1,'source_agency':'demo author'}}
    with sqlite3.connect(OUT/'foods.sqlite') as db:
        db.executescript('DROP TABLE IF EXISTS foods; DROP TABLE IF EXISTS aliases; CREATE TABLE foods(food_code TEXT PRIMARY KEY, food_name TEXT, origin TEXT,basis_unit TEXT,record_json TEXT); CREATE TABLE aliases(normalized_alias TEXT,food_code TEXT,alias TEXT);')
        db.execute('INSERT INTO foods VALUES(?,?,?,?,?)',('DEMO-001','가상음식','synthetic','g',json.dumps(food)))
        db.execute('INSERT INTO aliases VALUES(?,?,?)',('가상음식','DEMO-001','가상음식'))
    with sqlite3.connect(OUT/'nutrient_references.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS reference_intakes(record_json TEXT)')
    defs=[{'nutrient_id':key,'name':name,'unit':unit} for key,name,unit in [('R','에너지','kcal'),('T','단백질','g'),('AD','나트륨','mg'),('EU','카페인','mg')]]
    for name,value in [('food_nutrient_definitions.json',defs),('nutrient_reference_definitions.json',[]),('caffeine_rules.json',{})]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    (OUT/'documents.jsonl').write_text(''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in docs))
    print('가상 데이터 생성 완료. 실제 영양소 섭취기준은 포함하지 않습니다.')


if __name__=='__main__':main()
