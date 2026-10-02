"""Conservative item-to-quantity binding for supported intake expressions.

Unclear ownership is rejected, not repaired. This is not a general Korean parser.
"""
from decimal import Decimal
import re

COUNTS={'한':1,'두':2,'세':3,'네':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9,'열':10}
COUNT_UNITS={'캡슐','인분','잔','정','개','캔'}
NUTRIENTS={'caffeine':'카페인','sodium':'나트륨','calcium':'칼슘','magnesium':'마그네슘','iron':'철','potassium':'칼륨','zinc':'아연'}


def aliases(item):
    result=[]
    nutrient=item.nutrient_id or ''
    if nutrient.startswith('vitamin_'):
        suffix=re.escape(nutrient.removeprefix('vitamin_'))
        result += [r'비타민\s*'+suffix+r'(?![A-Za-z0-9])',r'vitamin\s*'+suffix+r'(?![A-Za-z0-9])']
    if nutrient in NUTRIENTS:result.append(re.escape(NUTRIENTS[nutrient]))
    if item.name and (len(item.name)>1 or not result):
        result.append(r'[\s_]*'.join(re.escape(x) for x in re.split(r'[\s_]+',item.name) if x))
    if item.food_code:result.append(re.escape(item.food_code))
    return result


def bound_issue(question,item,all_items,quantity_pattern,canonical_unit):
    """Return an explanation on ambiguity/mismatch; None only for a supported binding."""
    own=aliases(item)
    if not own:return '항목명을 원문에서 확인할 수 없습니다.'
    owners=list(re.finditer('|'.join('(?:'+p+')' for p in own),question,re.I))
    if not owners:return '해당 음식/성분의 이름과 수치를 함께 다시 입력해주세요.'
    # Never borrow a number from a later nutrient, another item, or profile field.
    other=[p for x in all_items if x is not item for p in aliases(x)]
    foreign=r'비타민\s*[A-Za-z](?:\d+)?|vitamin\s*[A-Za-z](?:\d+)?|카페인|나트륨|칼슘|마그네슘|체중|몸무게|신장|나이'
    boundaries=list(re.finditer('|'.join([foreign,*other]),question,re.I))
    matches=[]
    for owner in owners:
        stop=min([m.start() for m in boundaries if m.start()>=owner.end()]+[m.start() for m in owners if m.start()>=owner.end()]+[len(question)])
        segment=question[owner.end():stop]
        # End at the first completed-consumption clause or sentence, keeping decimal dots.
        end=re.search(r'먹었|마셨|섭취했|복용했|(?<!\d)[.!?]|[.!?](?!\d)',segment)
        if end:segment=segment[:end.start()]
        quantities=[]
        for m in quantity_pattern.finditer(segment):
            value=Decimal(re.sub(r'\s|,','',m.group(1)).replace('−','-').replace('－','-'))
            quantities.append((value,canonical_unit(m.group(2)),m.start(),m.end()))
        for m in re.finditer(r'(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(캡슐|잔|정|개|캔)',segment):
            quantities.append((Decimal(COUNTS[m.group(1)]),m.group(2),m.start(),m.end()))
        if item.amount is None or item.unit is None:
            continue  # No arithmetic is possible; the calculator will request details.
        wanted=(Decimal(str(item.amount)),canonical_unit(item.unit))
        selected=[q for q in quantities if q[:2]==wanted]
        if not selected:continue
        for chosen in selected:
            # Per-tablet/can label counts are not consumed counts.
            counts=[q[0] for q in quantities if q[1] in COUNT_UNITS and q!=chosen and not re.match(r'\s*당',segment[q[3]:])]
            total=bool(re.search(r'(?:총|총량(?:은|으로)?|합계)\s*$',segment[:chosen[2]]))
            if total:
                expected=Decimal(1)
            elif counts:
                if len(set(counts))!=1:return '같은 항목의 개수가 여러 개라 적용할 수 없습니다. 표시 함량과 실제 개수를 분리해서 알려주세요.'
                expected=counts[0]
            else:
                expected=Decimal(1)
            matches.append((wanted,expected))
    if item.amount is None or item.unit is None:return None
    if not matches:return '수치가 해당 음식/성분에 연결되지 않습니다. 체중이나 다른 항목의 값을 섭취량으로 사용하지 않습니다.'
    if len(set(matches))!=1:return '해당 항목의 수치·개수 연결이 모호합니다. 항목별로 다시 입력해주세요.'
    if Decimal(str(item.count))!=matches[0][1]:
        return '해당 항목의 실제 개수가 추출값과 다릅니다. 총량과 1개당 함량·개수를 구분해서 알려주세요.'
    return None
