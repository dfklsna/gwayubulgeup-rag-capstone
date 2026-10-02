"""Extract KDRI 2025 summary tables by PDF coordinates, retaining all conditions.

No LLM, OCR, inferred missing values, or disease-specific advice is used.
Rebuild: .venv/bin/python scripts/prepare_reference_intakes.py
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import pdfplumber

BASE = Path(__file__).resolve().parents[1]
OUT = BASE/'data/prepared'
COLLECTION = BASE.parent/'collection_runs/20261002'
DOC_ID = 'KR_KDRI_2025__5a5567abef16'
EXPECTED_AGES = ['0-5','6-11','1-2','3-5'] + ['6-8','9-11','12-14','15-18','19-29','30-49','50-64','65-74','75']*2
TYPES = ['EAR','RNI','AI','UL']
# IDs are independent of Excel column letters; forms and scopes are kept separate.
NUTRIENTS = {}

def nutrient(key, name, unit, columns=(), factors=None, **extra):
    NUTRIENTS[key] = {'nutrient_id':key,'name':name,'unit':unit,
        'food_columns':list(columns),'food_factors':factors or ['1']*len(columns),**extra}

for args in [
 ('energy','에너지','kcal',['R']),('carbohydrate','탄수화물','g',['W']),('fiber','식이섬유','g',['Y']),
 ('fat','지방','g',['U']),('linoleic_acid','리놀레산','g',['CG']),('alpha_linolenic_acid','알파-리놀렌산','g',['CQ']),
 ('epa_dha','EPA+DHA','mg',['BW']),('dha','DHA','mg',['CC']),('protein','단백질','g',['T']),
 ('methionine_cysteine','메티오닌+시스테인','g',['ED','EG'],['0.001','0.001']),
 ('leucine','류신','g',['EC'],['0.001']),('isoleucine','이소류신','g',['EK'],['0.001']),
 ('valine','발린','g',['EE'],['0.001']),('lysine','라이신','g',['EB'],['0.001']),
 ('phenylalanine_tyrosine','페닐알라닌+티로신','g',['EP','EO'],['0.001','0.001']),
 ('threonine','트레오닌','g',['EM'],['0.001']),('tryptophan','트립토판','g',['EN'],['0.001']),
 ('histidine','히스티딘','g',['ER'],['0.001']),('water_liquid','액체 수분','ml',[]),('water_total','총수분','ml',[]),
 ('vitamin_a','비타민 A','ug_RAE',['AE']),('vitamin_d','비타민 D','ug',['AL']),('vitamin_e','비타민 E','mg_alpha_TE',['AZ']),
 ('vitamin_k','비타민 K','ug',['BI']),('vitamin_c','비타민 C','mg',['AK']),('thiamin','티아민','mg',['AH']),
 ('riboflavin','리보플라빈','mg',['AI']),('niacin','니아신','mg_NE',[]),
 ('nicotinic_acid','니코틴산','mg',[]),('nicotinamide','니코틴아미드','mg',[]),
 ('vitamin_b6','비타민 B6','mg',['AS']),('folate','엽산','ug_DFE',['AU']),('folic_acid','강화식품·보충제 엽산','ug',[]),
 ('vitamin_b12','비타민 B12','ug',['AT']),('pantothenic_acid','판토텐산','mg',['AW']),('biotin','비오틴','ug',['AR']),
 ('choline','콜린','mg',['AV']),('calcium','칼슘','mg',['Z']),('phosphorus','인','mg',['AB']),
 ('sodium','나트륨','mg',['AD']),('chloride','염소','mg',['DT']),('potassium','칼륨','mg',['AC']),
 ('magnesium','마그네슘','mg',['DN']),('iron','철','mg',['AA']),('zinc','아연','mg',['DS']),
 ('copper','구리','ug',['DM']),('fluoride','불소','mg',['DQ']),('manganese','망간','mg',['DO']),
 ('iodine','요오드','ug',['DU']),('selenium','셀레늄','ug',['DR']),('molybdenum','몰리브덴','ug',['DP']),('chromium','크롬','ug',['DV']),
 ('saturated_fat','포화지방산','g',['AN']),('trans_fat','트랜스지방산','g',['AO']),
 ('total_sugar','총당류','g',['X']),('added_sugar','첨가당','g',[]),('cholesterol','콜레스테롤','mg',['AM'])]:
    nutrient(*args)
NUTRIENTS['niacin']['food_mapping_note']='DB 니아신(mg)은 니아신당량(mg NE)과 동일하다고 가정하지 않음. 트립토판 전환·DB 함량 정의 확인 후 연결.'
NUTRIENTS['water_total']['food_mapping_note']='DB 수분(g)을 mL로 자동 변환하지 않음; 음식 수분 외 음료도 필요.'
NUTRIENTS['water_liquid']['food_mapping_note']='물·음료·우유의 별도 액체 섭취 기록 필요.'
NUTRIENTS['added_sugar']['food_mapping_note']='총당류(X)로 첨가당을 대체하지 않음.'
NUTRIENTS['folic_acid']['food_mapping_note']='식이엽산당량(AU)과 직접 비교 불가. 강화식품/보충제의 합성 엽산량 필요.'
for k in ('nicotinic_acid','nicotinamide'):
    NUTRIENTS[k]['food_mapping_note']='DB 성분값만으로 자연식품/강화식품/보충제 유래를 구분할 수 없어 자동 비교 보류.'

def four(*ids):
    return [(key, kind) for key in ids for kind in TYPES]

SPECS = {
 (11,0):[(n,'AMDR') for n in ('carbohydrate','protein','fat','saturated_fat','trans_fat')],
 (12,0):[('energy',k) for k in ('EER','RNI','AI','UL')]+four('carbohydrate','fiber'),
 (12,1):four('fat','linoleic_acid','alpha_linolenic_acid','epa_dha'),
 (13,0):four('protein','methionine_cysteine','leucine'),(13,1):four('isoleucine','valine','lysine'),
 (14,0):four('phenylalanine_tyrosine','threonine','tryptophan'),
 (14,1):four('histidine')+[('water_liquid','AI'),('water_total','AI'),('water_total','UL')],
 (15,0):four('vitamin_a','vitamin_d'),(15,1):four('vitamin_e','vitamin_k'),
 (16,0):four('vitamin_c','thiamin'),(16,1):four('riboflavin','niacin'),
 (17,0):four('vitamin_b6')+[('folate',k) for k in TYPES[:3]]+[('folic_acid','UL')],
 (17,1):four('vitamin_b12','pantothenic_acid','biotin'),(18,0):four('choline'),
 (19,0):four('calcium','phosphorus')+[('sodium',k) for k in ('EAR','RNI','AI','CDRR')],
 (19,1):four('chloride','potassium','magnesium'),(20,0):four('iron','zinc','copper'),
 (20,1):four('fluoride','manganese','iodine'),(21,0):four('selenium','molybdenum','chromium')}


def write_json(name, obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def write_jsonl(name, rows):
    (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))


def char_lines(chars):
    groups=[]
    for c in sorted(chars,key=lambda c:(c['top'],c['x0'])):
        if not groups or abs(groups[-1][0]['top']-c['top'])>1:
            groups.append([])
        groups[-1].append(c)
    return '\n'.join(v for g in groups if (v:=''.join(c['text'] for c in sorted(g,key=lambda c:c['x0'])).strip()))


def demographic(i):
    if i>=22:
        return {'sex':'female','life_stage':'pregnancy' if i==22 else 'lactation',
                'age_min_months':None,'age_max_months_exclusive':None,'age_label':'원문 특수행: 연령 별도 미기재','trimester':None}
    label=EXPECTED_AGES[i]
    lo,hi=(75,None) if label=='75' else map(int,label.split('-'))
    return {'sex':'both' if i<4 else ('male' if i<13 else 'female'),'life_stage':'general',
            'age_min_months':lo if i<2 else lo*12,'age_max_months_exclusive':None if hi is None else ((hi+1) if i<2 else (hi+1)*12),
            'age_label':label+('개월' if i<2 else '세'),'trimester':None}


def extract_cells(doc):
    cells=[];pages={}
    with pdfplumber.open(COLLECTION/doc['raw_path']) as pdf:
        for pn in range(11,22):
            page=pdf.pages[pn-1];words=page.extract_words(x_tolerance=1,y_tolerance=2)
            pages[pn]={'pdf_page':pn,'text':page.extract_text(layout=True),'width':page.width,'height':page.height}
            heads=[w for w in words if w['text']=='연령' and w['x0']>105 and w['top']<640]
            for bi,h in enumerate(heads):
                spec=SPECS[(pn,bi)]
                end=heads[bi+1]['top']-15 if bi+1<len(heads) else 700
                hw=[w for w in words if h['top']-2<=w['top']<=h['top']+19 and w['x0']>h['x1']]
                allowed=['탄수화물','단백질','지방','포화지방산','트랜스지방산'] if pn==11 else (['평균','권장','충분','상한','액체2)','총수분3)'] if (pn,bi)==(14,1) else ['평균','권장','충분','상한','필요','상한섭취량','만성질환'])
                cols=sorted([w for w in hw if w['text'] in allowed],key=lambda w:w['x0'])
                assert len(cols)==len(spec),(pn,bi,len(cols),len(spec))
                xs=[(w['x0']+w['x1'])/2 for w in cols]
                edges=[xs[0]-(xs[1]-xs[0])/2]+[(a+b)/2 for a,b in zip(xs,xs[1:])]+[xs[-1]+(xs[-1]-xs[-2])/2]
                ages=[w for w in words if h['top']+14<w['top']<end and w['x0']<edges[0] and (re.fullmatch(r'\d+-\d+',w['text']) or w['text']=='75')]
                assert [w['text'] for w in ages]==EXPECTED_AGES,(pn,bi)
                specials=[w for w in words if h['top']+14<w['top']<end and w['x0']<edges[0] and re.fullmatch(r'(임신부|수유부)(1\))?',w['text'])]
                assert len(specials)==2
                horizontal=sorted(set(e['top'] for e in page.horizontal_edges if e['x1']-e['x0']>200))
                for ri,a in enumerate(ages+specials):
                    cy=(a['top']+a['bottom'])/2
                    lo,hi=(a['top']-2,a['bottom']+1) if ri<22 else (max(y for y in horizontal if y<cy),min(y for y in horizontal if y>cy))
                    for ci,(key,kind) in enumerate(spec):
                        chars=[c for c in page.chars if edges[ci]<(c['x0']+c['x1'])/2<edges[ci+1] and lo<(c['top']+c['bottom'])/2<hi]
                        cells.append({'cell_id':f'p{pn}_t{bi+1}_r{ri+1}_c{ci+1}','pdf_page':pn,'table':bi+1,'row':ri+1,'column':ci+1,
                            'bbox':[round(x,3) for x in (edges[ci],lo,edges[ci+1],hi)],'column_header_raw':cols[ci]['text'],
                            'nutrient_id':key,'reference_type':kind,'demographic':demographic(ri),
                            'raw_text_with_footnotes':char_lines(chars),'value_text':char_lines([c for c in chars if c['size']>=6])})
    assert len(cells)==sum(len(s)*24 for s in SPECS.values())
    return cells,pages


def parse_value(raw):
    value=raw.replace(',','').strip()
    base={'value':None,'min_value':None,'max_value':None,'value_mode':'absolute','status':'numeric','comparator':'reference'}
    if value in ('','-'):
        return {**base,'status':'not_established_in_table','reason':'blank' if value=='' else 'dash'}
    if value=='±0':
        return {**base,'value_mode':'inherit_age_matched_female','status':'inherit'}
    if re.fullmatch(r'\d+(?:\.\d+)?-\d+(?:\.\d+)?',value):
        low,high=map(float,value.split('-'))
        return {**base,'min_value':low,'max_value':high,'comparator':'inclusive_range'}
    if value.endswith('미만'):
        return {**base,'max_value':float(value.replace('미만','').strip()),'comparator':'lt'}
    assert re.fullmatch(r'\+?\d+(?:\.\d+)?',value),repr(raw)
    return {**base,'value':float(value),'value_mode':'add_to_age_matched_female' if value.startswith('+') else 'absolute'}


def build_rules(cells,doc):
    records=[]
    for cell in cells:
        variants=[(cell['nutrient_id'],cell['value_text'],None,'')]
        raw=cell['value_text'];key=cell['nutrient_id'];kind=cell['reference_type'];demo=cell['demographic']
        if key=='niacin' and kind=='UL':
            vals=raw.split('/') if raw else ['','']
            assert len(vals)==2
            variants=[('nicotinic_acid',vals[0],None,'acid'),('nicotinamide',vals[1],None,'amide')]
        if key=='energy' and demo['life_stage']=='pregnancy' and raw:
            assert raw.splitlines()==['+0','+340','+450']
            variants=[(key,v,i+1,f'trimester{i+1}') for i,v in enumerate(raw.splitlines())]
        if key=='protein' and kind in ('EAR','RNI') and demo['life_stage']=='pregnancy' and raw:
            vals=raw.splitlines();assert len(vals)==2
            variants=[(key,v,i+2,f'trimester{i+2}') for i,v in enumerate(vals)]
        if key=='epa_dha' and kind=='AI':
            if cell['row']<=2:variants=[('dha',raw,None,'dha')]
            elif demo['life_stage']!='general':
                assert raw=='300\n(200)'
                variants=[('epa_dha','300',None,'epa_dha'),('dha','200',None,'dha_component')]
        for key,value,trimester,suffix in variants:
            rule={'reference_id':'KDRI2025_'+cell['cell_id']+('_'+suffix if suffix else ''),
                  'nutrient_id':key,'nutrient_name':NUTRIENTS[key]['name'],'reference_type':kind,
                  'unit':'percent_energy' if kind=='AMDR' else NUTRIENTS[key]['unit'],
                  'period':'day','population':'generally_healthy_population','demographic':{**demo,'trimester':trimester},
                  **parse_value(value),'intake_scope':'total_intake','auto_food_comparison':bool(NUTRIENTS[key]['food_columns']),
                  'interpretation':'RNI/EAR/AI are adequacy references, not excess thresholds; UL and CDRR have distinct meanings.',
                  'source':{'source_id':'KR_KDRI_2025','document_id':DOC_ID,'raw_sha256':doc['raw_sha256'],
                            'url':doc['url'],'pdf_page':cell['pdf_page'],'cell_id':cell['cell_id'],'bbox':cell['bbox'],
                            'page_text_record':f'kdri_reference_pages.jsonl#page={cell["pdf_page"]}','raw_cell_text':cell['raw_text_with_footnotes']}}
            if kind=='UL' and key in ('vitamin_a','vitamin_e'):
                rule.update(auto_food_comparison=False,intake_scope='form_scope_review_required',
                            comparison_block_reason='총 활성당량만으로 상한을 자동 판정하지 않음. 원문 제형·급원 적용 범위 검토 필요.')
            if kind=='UL' and key=='magnesium':
                rule.update(auto_food_comparison=False,intake_scope='non_food_sources',
                            comparison_block_reason='식품 외 급원(보충제·의약품)의 상한. 음식 마그네슘에 적용하지 않음.')
            if key=='folic_acid':rule['intake_scope']='fortified_foods_and_supplements'
            if key in ('nicotinic_acid','nicotinamide'):rule['intake_scope']='fortified_foods_and_supplements_form_specific'
            if key=='dha' and suffix=='dha_component':rule['component_of']='epa_dha'
            if kind=='EER':rule['interpretation']='연령·성별 집단 참고값. 체격·활동량을 반영한 개인별 에너지 필요량 계산과 구별.'
            records.append(rule)
    # Text recommendations on page 11 are not ULs. Preserve inequality semantics.
    for key,limit,unit,comparator,age_min,scope in [('total_sugar',20,'percent_energy','le',None,'total_dietary_sugar'),('added_sugar',10,'percent_energy','le',None,'added_sugar_only'),('cholesterol',300,'mg','lt',228,'dietary_intake')]:
        records.append({'reference_id':'KDRI2025_p11_guideline_'+key,'nutrient_id':key,'nutrient_name':NUTRIENTS[key]['name'],
            'reference_type':'recommendation','unit':unit,'period':'day','population':'generally_healthy_population',
            'demographic':{'sex':'both','life_stage':'all','age_min_months':age_min,'age_max_months_exclusive':None,'age_label':'19세 이상' if age_min else '원문 문장에 연령 미기재','trimester':None},
            'status':'numeric','value':None,'min_value':None,'max_value':float(limit),'comparator':comparator,'value_mode':'absolute',
            'intake_scope':scope,'auto_food_comparison':bool(NUTRIENTS[key]['food_columns']),
            'interpretation':'식이 권고치이며 UL이 아님. 에너지 비율은 하루 전체 에너지 섭취량이 필요.',
            'source':{'source_id':'KR_KDRI_2025','document_id':DOC_ID,'raw_sha256':doc['raw_sha256'],'url':doc['url'],
                      'pdf_page':11,'cell_id':None,'bbox':None,'page_text_record':'kdri_reference_pages.jsonl#page=11',
                      'raw_cell_text': '콜레스테롤: 19세 이상 300 mg/일 미만 권고' if key=='cholesterol' else '총당류는 총 에너지섭취량의 20% 이내, 첨가당은 10% 이내 (원문 전체는 페이지 기록 참조)'}})
    return records


def main():
    docs=[json.loads(l) for l in (OUT/'documents.jsonl').read_text().splitlines()]
    doc=next(d for d in docs if d['document_id']==DOC_ID)
    assert hashlib.sha256((COLLECTION/doc['raw_path']).read_bytes()).hexdigest()==doc['raw_sha256']
    cells,pages=extract_cells(doc);records=build_rules(cells,doc)
    assert len({r['reference_id'] for r in records})==len(records)
    write_jsonl('kdri_reference_cells.jsonl',cells)
    write_jsonl('kdri_reference_pages.jsonl',[{'document_id':DOC_ID,**page} for page in pages.values()])
    write_jsonl('nutrient_reference_intakes.jsonl',records)
    write_json('nutrient_reference_definitions.json',list(NUTRIENTS.values()))
    temp=OUT/'nutrient_references.building.sqlite'
    if temp.exists():temp.unlink()
    with sqlite3.connect(temp) as db:
        db.execute('CREATE TABLE reference_intakes(reference_id TEXT PRIMARY KEY,nutrient_id TEXT,reference_type TEXT,sex TEXT,life_stage TEXT,age_min_months INTEGER,age_max_months_exclusive INTEGER,record_json TEXT)')
        db.executemany('INSERT INTO reference_intakes VALUES(?,?,?,?,?,?,?,?)',[(r['reference_id'],r['nutrient_id'],r['reference_type'],r['demographic']['sex'],r['demographic']['life_stage'],r['demographic']['age_min_months'],r['demographic']['age_max_months_exclusive'],json.dumps(r,ensure_ascii=False)) for r in records])
        db.execute('CREATE INDEX reference_lookup ON reference_intakes(nutrient_id,sex,life_stage,age_min_months)')
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    temp.replace(OUT/'nutrient_references.sqlite')
    summary={'status':'structured','source_document_id':DOC_ID,'source_pdf_pages':list(pages),'source_tables':len(SPECS),
             'source_cells':len(cells),'reference_records':len(records),'nutrient_or_form_count':len({r['nutrient_id'] for r in records}),
             'status_counts':dict(Counter(r['status'] for r in records)),'type_counts':dict(Counter(r['reference_type'] for r in records)),
             'food_mapped_nutrients':sum(bool(v['food_columns']) for v in NUTRIENTS.values()),
             'scope':'정오표 반영 국문 요약본 11–21쪽의 전체 요약표 및 당류/콜레스테롤 권고문. 질환별 치료 기준 및 개인별 EER 방정식은 포함하지 않음.',
             'source_sha256':doc['raw_sha256'],'parser_version':'pdfplumber '+pdfplumber.__version__,
            'limitations':['비타민 A/E 상한의 음식 자동 비교는 제형·급원 검토 전 보류.','니아신 mg와 mg NE, 식품 수분 g와 mL를 동일시하지 않음.','원문 공란/대시는 기준 미설정으로 보존. 무제한 섭취 가능이라는 뜻이 아님.','임신·수유 값의 +부가량과 절대 총량, 분기별 값을 구별.','하루 전체 식사 확인 없이 결핍·안전·임상적 위해를 단정하지 않음.']}
    write_json('nutrient_reference_summary.json',summary)
    write_json('nutrient_reference_policy.json',{
        'reference_types':{'EAR':'평균필요량: 과다 기준이 아님','RNI':'권장섭취량: 과다 기준이 아님','AI':'충분섭취량: 과다 기준이 아님',
            'UL':'상한섭취량: 영양소 형태와 적용 급원을 확인','CDRR':'만성질환위험감소섭취량: UL과 구별',
            'EER':'에너지필요추정량: 집단 표값과 개인별 방정식을 구별','AMDR':'에너지적정비율: 하루 총 에너지 필요',
            'recommendation':'원문 권고치: UL로 이름을 바꾸지 않음'},
        'age_interval':'완료 월령 기준 하한 포함, 상한 제외; 75세 이상은 상한 없음',
        'special_row_resolution':'임신·수유 +값은 같은 연령 여성 기준에 더함. 절대 총량은 더하지 않음. ±0은 해당 연령 여성 기준 상속.',
        'profile_guard':'임신·수유 12세 미만 자동 조회는 구현 범위 밖이며 원문 개별 검토 필요. 이 제한을 KDRI의 연령 기준으로 해석하지 않음.',
        'blank_or_dash':'기준표 미설정으로 보존; 0, 안전, 무제한이라는 뜻이 아님',
        'clinical_scope':'일반 건강인 참고 기준. 질환별 치료·약물 상호작용·개인별 EER 방정식 미구현.',
        'source_check_url':'https://www.kns.or.kr/fileroom/fileroom_view.asp?BoardID=Kdr&idx=167',
        'source_check_date':'2026-10-02'})
    lines=['영양소/성분 형태별 기준 목록','영양소/형태 | 단위 | 수치 기준 수 | 음식 DB 연결 열','']
    for key,d in NUTRIENTS.items():
        count=sum(r['nutrient_id']==key and r['status'] in ('numeric','inherit') for r in records)
        lines.append(f"{d['name']} ({key}) | {d['unit']} | {count} | {','.join(d['food_columns']) or '조건/추가 데이터 필요'}")
    (OUT/'영양소_기준표_목록.txt').write_text('\n'.join(lines)+'\n')
    document_count = sum(1 for line in (OUT/'all_documents.jsonl').open() if line.strip())
    food_count = json.loads((OUT/'food_preprocessing_summary.json').read_text())['food_records']
    report=f'''한국인 영양소 섭취기준 구조화 결과
자료: 정오표 반영 2025 KDRI 국문 요약본 PDF 11–21쪽, 19개 표 및 당류/콜레스테롤 권고문.
영양소·성분 형태: {summary['nutrient_or_form_count']}개 (건강 주제 수와 다름)
원본 셀: {len(cells):,}개 / 구조화 레코드: {len(records):,}개
수치 기준: {summary['status_counts']['numeric']:,}개 / 연령별 여성 기준 상속: 2개 / 미설정: {summary['status_counts']['not_established_in_table']:,}개
음식 DB 연결이 있는 성분: {summary['food_mapped_nutrients']}개. 연결이 있어도 기준 종류·섭취 맥락에 따라 비교 보류 가능.
문서 {document_count}개와 음식 DB {food_count:,}개는 변경하지 않음. 기준 레코드는 별도 데이터이며 문서 수에 합산하지 않음.

보존 항목
- 연령(개월 범위), 성별, 임신·수유, 임신 분기, 하루 기준 단위
- EAR/RNI/AI/UL/CDRR/EER/AMDR/권고치 구별
- 절대량·부가량·기준 상속·범위·미만·이내·미설정 구별
- 원문 문서 ID, 해시, 실제 PDF 페이지, 셀 좌표, 원문 숫자와 주석

검증: scripts/validate_reference_intakes.py 및 data/prepared/nutrient_reference_validation.json 참조.
418개 일반 연령·성별 행을 Poppler 추출 결과와 별도 대조. 임신·수유 등 특수행과 헤더·단위·주석은 PDF 11쪽 시각 검토 및 고정값 테스트.
건강 판정/임상 검증이나 RAG 성능 평가가 아님.

자동 비교 제한
- 비타민 A/E 상한: 원문 성분 형태·급원 적용 범위 검토 전 음식 자동 비교 보류.
- 마그네슘 UL: 식품 외 급원 기준이므로 음식 성분량에 적용하지 않음.
- 엽산 DFE와 합성 엽산, 니아신 mg와 mg NE, 총당류와 첨가당을 구별.
- 음식 수분 g와 기준 mL는 밀도 없이 자동 환산하지 않음.
- 임신 단백질의 1분기 값은 표에 별도로 없어 추정하지 않음.
- 한 음식만으로 하루 섭취 완료·부족·안전 여부를 단정하지 않음.
- 요약표 밖 질환별 치료 기준, 개인별 EER 방정식, 원문 문헌의 모든 수치는 이번 구조화 범위 밖.

파일
nutrient_reference_intakes.jsonl / nutrient_references.sqlite: 기준 데이터
nutrient_reference_definitions.json / nutrient_reference_policy.json: 성분 연결과 적용 규칙
kdri_reference_cells.jsonl / kdri_reference_pages.jsonl: 원문 셀·페이지 감사 기록
food_reference_example_jellyfish_400g.json: 가상의 30세 남성 조건으로 계산한 DB 음식 400g 비교 예시 (사용자 프로필 아님)

재실행 (rag_capstone에서)
.venv/bin/python scripts/prepare_reference_intakes.py
.venv/bin/python scripts/validate_reference_intakes.py
.venv/bin/python scripts/refresh_prepared_catalog.py
기준 조회:
.venv/bin/python scripts/query_reference_intakes.py --nutrient sodium --age-years 30 --sex male
음식 비교:
.venv/bin/python scripts/query_reference_intakes.py --food-code D314-612380000-0001 --amount 400 --unit g --age-years 30 --sex male
'''
    (BASE/'results/nutrient_reference_report.txt').write_text(report)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
