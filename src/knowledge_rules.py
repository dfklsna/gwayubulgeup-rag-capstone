"""Bounded, source-anchored concepts. No question IDs or evaluation labels are used.

Rules provide reviewed paraphrases only while their exact source chunks are present.
This is curated knowledge + deterministic calculation, not free-form generation.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

CATALOG = Path(__file__).with_name('knowledge_sources.json')


def concept_for(question):
    q = re.sub(r'\s+', '', question).casefold()
    if re.search(r'나트륨|sodium', q) and re.search(r'소금|salt|염화나트륨', q):
        return 'salt_equivalent'
    if '첨가당' in q and re.search(r'당류|설탕|표시|표기|의무', q):
        return 'sugars'
    if re.search(r'권장량|권장섭취량|충분섭취량|평균필요량|\bai\b|\brni\b|\bear\b', question, re.I) and re.search(r'상한|\bul\b|과다|과잉', question, re.I):
        return 'reference_types'
    if re.search(r'카페인|caffeine', q) and re.search(r'합[쳐산]|함께|따로|더해|총량|여러급원', q):
        return 'caffeine_sources'
    return None


def bind_sources(concept, chunks, catalog=None):
    catalog = catalog if catalog is not None else json.loads(CATALOG.read_text())
    spec = catalog['concepts'][concept]
    by_id = {c['chunk_id']:c for c in chunks}
    hits=[]
    for anchor in spec['sources']:
        chunk=by_id.get(anchor['chunk_id'])
        if chunk is None or hashlib.sha256(chunk['text'].encode()).hexdigest()!=anchor['text_sha256']:
            return [], spec
        hits.append(dict(chunk, citation=f'D{len(hits)+1}', score=None))
    return hits, spec


def salt_equivalent(amount, unit, kind, factor):
    """Public-health approximate salt equivalent, not measured product composition."""
    amount=Decimal(str(amount));factor=Decimal(str(factor))
    if not amount.is_finite() or amount<=0 or not factor.is_finite() or factor<=0:
        raise ValueError('양수의 유한한 질량과 환산계수가 필요합니다.')
    if unit not in ('mg','g') or kind not in ('sodium','salt'):
        raise ValueError('나트륨/소금과 mg/g 단위를 확인해주세요.')
    mg=amount*(1000 if unit=='g' else 1)
    target=mg*factor if kind=='sodium' else mg/factor
    return {'kind':kind,'input_amount':str(amount),'input_unit':unit,
            'output_kind':'salt' if kind=='sodium' else 'sodium',
            'output_amount_mg':str(target),'factor_salt_per_sodium':str(factor),
            'approximate':True,'scope':'salt_equivalent_not_product_composition'}


def fmt(value):
    return format(Decimal(str(value)).normalize(),'f')


def render_concept(question, chunks, catalog=None):
    concept=concept_for(question)
    if concept is None:return None
    hits,spec=bind_sources(concept,chunks,catalog)
    result={'concept':concept,'hits':hits,'calculation':None,'status':'answered'}
    if not hits:
        result.update(status='source_unavailable',answer='이 개념의 검증된 원문이 없거나 변경되어 설명·환산을 보류합니다. 출처를 다시 확인해야 합니다.')
        return result
    if concept=='reference_types':
        text=('권장섭취량(RNI)·평균필요량(EAR)·충분섭취량(AI)은 섭취부족을 평가하는 기준이며 상한섭취량(UL)과 목적이 다릅니다. '
              '따라서 권장량이나 충분섭취량을 넘었다는 사실만으로 UL 초과라고 판단하지 않습니다. [D1]\n'
              'UL이 제시되지 않았다고 위해 가능성이 없다는 뜻은 아니며, UL 이하여도 모든 개인의 안전을 보장하지 않습니다. [D1][D2]\n'
              '실제 비교에는 성분명, 나이·성별·임신·수유 여부, 성분 형태·급원 및 하루 총섭취량을 확인해야 합니다.')
    elif concept=='sugars':
        text=('총당류에는 식품에 원래 들어 있는 당과 조리·가공 중 첨가된 당이 포함됩니다. '
              '총당류와 첨가당은 같은 개념이 아니므로 총당류 양만으로 첨가당 양을 확정할 수 없습니다. [D1]\n'
              '첨가당 양은 해당 제품의 구체적인 성분 정보를 추가로 확인해야 합니다.')
        if re.search(r'의무|법|규정|표시해야|표기해야',question):
            text+='\n현재 확인한 근거는 영양 개념 설명입니다. 법적 표시 의무는 적용 국가·제품·현행 규정 근거가 없어 답변을 보류합니다.'
    elif concept=='caffeine_sources':
        text=('커피·에너지음료·초콜릿·영양제 등 여러 급원에서 섭취한 카페인을 함께 고려해야 합니다. '
              '신체는 자연적으로 존재하는 카페인과 첨가된 카페인을 다르게 처리하지 않습니다. [D1]\n'
              '제품별 표시 카페인 함량과 실제 섭취량을 확인해주세요. 함량이 없는 제품의 값을 추정하지 않습니다.')
    else:
        factor=spec['salt_per_sodium']
        text=('나트륨 질량과 소금 질량은 같지 않습니다. 소금 환산량은 나트륨 질량의 약 '+fmt(factor)+'배로 계산합니다. [D1]\n'
              '이는 근사적인 소금 환산량이며 제품의 실제 소금 함량을 측정한 값은 아닙니다.')
        # Bind each quantity to the adjacent named substance, never to arbitrary numbers.
        pattern=r'(나트륨|sodium|소금|salt)(?:은|는|의|이|을|으로|\s)*([+−－-]?[\d,]+(?:\.\d+)?)\s*(mg|g|밀리그램|그램)(?![A-Za-z])'
        matches=re.findall(pattern,question,re.I)
        rows=[]
        try:
            for name,value,unit in matches:
                unit={'밀리그램':'mg','그램':'g'}.get(unit.casefold(),unit.casefold())
                row=salt_equivalent(value.replace(',','').replace('−','-').replace('－','-'),unit,
                                    'sodium' if name.casefold() in ('나트륨','sodium') else 'salt',factor)
                rows.append(row)
        except (ValueError,InvalidOperation):
            result.update(status='needs_clarification',answer='환산할 질량은 양수여야 합니다. 나트륨 또는 소금의 실제 mg/g 값을 다시 알려주세요.')
            return result
        if rows:
            result['calculation']={'type':'salt_equivalent','rows':rows,'source_ids':[h['source_id'] for h in hits]}
            for row in rows:
                source='나트륨' if row['kind']=='sodium' else '소금'
                target='소금 환산량' if row['kind']=='sodium' else '나트륨 환산량'
                text+=f"\n- {source} {fmt(row['input_amount'])}{row['input_unit']} → {target} 약 {fmt(row['output_amount_mg'])}mg [T1][D1]"
        elif re.search(r'\d',question):
            text+='\n개별 환산은 “나트륨 100mg” 또는 “소금 1g”처럼 대상과 질량을 붙여 입력해주세요.'
    result['answer']=text
    return result
