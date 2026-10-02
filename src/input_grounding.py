"""Conservative item-to-quantity binding for supported intake expressions.

Unclear ownership is rejected, not repaired. This is not a general Korean parser.
"""
from decimal import Decimal
import re

COUNTS={'한':1,'두':2,'세':3,'네':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9,'열':10}
COUNT_UNITS={'캡슐','인분','잔','정','개','캔'}
# Trusted identifiers and aliases, not names supplied by the extraction model.
NUTRIENTS={'caffeine':('카페인',), 'sodium':('나트륨',), 'calcium':('칼슘',),
           'magnesium':('마그네슘',), 'iron':('철','철분'), 'potassium':('칼륨',),
           'zinc':('아연',), 'phosphorus':('인',), 'copper':('구리',),
           'selenium':('셀레늄',), 'iodine':('요오드',), 'manganese':('망간',),
           'folate':('엽산',), 'folic_acid':('폴산',), 'niacin':('니아신',),
           'nicotinic_acid':('니코틴산',), 'nicotinamide':('니코틴아미드',),
           'thiamin':('티아민','비타민 B1'), 'riboflavin':('리보플라빈','비타민 B2'),
           'pantothenic_acid':('판토텐산',), 'biotin':('비오틴',), 'choline':('콜린',),
           'protein':('단백질',), 'carbohydrate':('탄수화물',), 'fat':('지방',),
           'fiber':('식이섬유',), 'total_sugar':('총당류','당류'),
           'added_sugar':('첨가당',), 'cholesterol':('콜레스테롤',)}
VITAMINS={'vitamin_'+x for x in ('a','c','d','e','k','b6','b12')}


def nutrient_aliases(nutrient):
    if nutrient not in NUTRIENTS and nutrient not in VITAMINS:
        return []  # Unmapped IDs must be clarified; raw model names are not proof.
    result=[r'(?<![A-Za-z0-9_])'+re.escape(nutrient)+r'(?![A-Za-z0-9_])']
    names=NUTRIENTS.get(nutrient,())
    if nutrient in VITAMINS:
        suffix=nutrient.removeprefix('vitamin_')
        names=('비타민 '+suffix,'vitamin '+suffix)
    for name in names:
        pattern=r'\s*'.join(re.escape(x) for x in name.split())
        # Avoid matching C inside C2, or 철 inside an unrelated Korean word.
        result.append(r'(?<![A-Za-z가-힣])'+pattern+r'(?![A-Za-z0-9_])')
    return result


def aliases(item):
    if item.kind=='nutrient':
        return nutrient_aliases(item.nutrient_id)
    result=[]
    if item.name:
        result.append(r'[\s_]*'.join(re.escape(x) for x in re.split(r'[\s_]+',item.name) if x))
    if item.food_code:result.append(re.escape(item.food_code))
    return result


def quantities_in(segment, quantity_pattern, canonical_unit):
    quantities=[]
    for m in quantity_pattern.finditer(segment):
        value=Decimal(re.sub(r'\s|,','',m.group(1)).replace('−','-').replace('－','-'))
        quantities.append((value,canonical_unit(m.group(2)),m.start(),m.end()))
    for m in re.finditer(r'(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(캡슐|잔|정|개|캔)',segment):
        quantities.append((Decimal(COUNTS[m.group(1)]),m.group(2),m.start(),m.end()))
    return sorted(quantities,key=lambda q:q[2])


def coverage_issue(question, items, quantity_pattern, canonical_unit):
    """Require each quantity in an explicit intake clause to have its own item.

    Scan source clauses, including those before the first extracted item. Counts
    attached to a mass are handled by bound_issue; explicit profile/reference
    fields are not intake candidates. Ambiguous unmatched spans cause abstention.
    """
    candidates=[]
    start=0
    events=re.finditer(r'먹었|마셨|섭취했|복용했|(?<!\d)[.!?]|[.!?](?!\d)|[;\n]',question)
    for event in events:
        if event.group() not in ('먹었','마셨','섭취했','복용했'):
            start=event.end()
            continue
        segment=question[start:event.start()]
        offset=start
        start=event.end()
        # Conditional reports are already handled by the intent validator.
        if re.match(r'(?:다)?면',question[event.end():]):
            continue
        quantities=quantities_in(segment,quantity_pattern,canonical_unit)
        mass=[q for q in quantities if q[1] not in COUNT_UNITS]
        previous=0
        for q in mass or quantities:
            prefix=segment[previous:q[2]]
            suffix=segment[q[3]:]
            begin=previous
            previous=q[3]
            profile=re.search(r'(?:체중|몸무게|신장|나이)(?:은|는|이|가|:|\s)*$',prefix)
            reference=(re.search(r'(?:\bUL\b|상한(?:섭취량)?|권고(?:량)?|기준(?:값|량)?)(?:은|는|이|가|:|\s)*$',prefix,re.I)
                       or re.match(r'\s*(?:은|는|이|가)?\s*(?:상한|권고|기준|\bUL\b)',suffix,re.I))
            if profile or reference:
                continue
            candidates.append((q[0],q[1],offset+begin,offset+q[2]))
    edges=[]
    for amount,unit,begin,end in candidates:
        possible=[]
        for index,item in enumerate(items):
            patterns=aliases(item)
            if not patterns or item.amount is None or item.unit is None:
                continue
            if (Decimal(str(item.amount)),canonical_unit(item.unit))!=(amount,unit):
                continue
            if re.search('|'.join(patterns),question[begin:end],re.I):
                possible.append(index)
        edges.append(possible)
    # One extracted item cannot cover two independently reported source amounts.
    assigned={}
    def match(candidate,seen):
        for item in edges[candidate]:
            if item in seen:
                continue
            seen.add(item)
            if item not in assigned or match(assigned[item],seen):
                assigned[item]=candidate
                return True
        return False
    if any(not match(index,set()) for index in range(len(edges))):
        if candidates and all(unit in COUNT_UNITS for _,unit,_,_ in candidates):
            return '잔·정·인분의 용량이나 제품 표시 성분 함량이 필요합니다. 항목별 실제 섭취량과 제품 정보를 알려주세요.'
        return '원문에 추출 결과가 설명하지 못하는 섭취 항목이 남아 있습니다. 음식·성분과 섭취량을 빠짐없이 한 항목씩 입력해주세요.'
    return None


def count_tail_is_clear(segment, end, counts):
    """Only a bare count continuation may cross a completed consumption clause.

    Unknown item names, negations, corrections or multiple competing counts are
    deliberately not interpreted as a count belonging to the preceding item.
    """
    tail=segment[end:]
    # Mask quantities; the remaining supported grammar must be count-only.
    for q in reversed(counts):
        if q[2]>=end:
            start,stop=q[2]-end,q[3]-end
            tail=tail[:start]+' COUNT '+tail[stop:]
    # A separate, number-free comparison request does not change the count.
    tail=re.sub(r'(?:상한\s*)?(?:기준|상한섭취량|UL)(?:과|을|도)?\s*'
                r'(?:비교해줘|비교해주세요|알려줘)[.!?\s]*$', '',tail,flags=re.I)
    return re.fullmatch(
        r'(?:(?:먹었|마셨|섭취했|복용했)(?:어|어요|습니다|다)|'
        r'COUNT|총|총량|개수|갯수|실제로|먹은|마신|섭취한|복용한|것은|양은|'
        r'은|는|이야|이었어|였어|입니다|이에요|예요|[\s.,!?])*',tail) is not None


def bound_issue(question,item,all_items,quantity_pattern,canonical_unit):
    """Return an explanation on ambiguity/mismatch; None only for a supported binding."""
    if item.kind=='nutrient':
        # A truthful display name must not legitimize a different calculation ID.
        named={key for key in (*NUTRIENTS,*VITAMINS)
               if re.search('|'.join(nutrient_aliases(key)),item.name,re.I)}
        if named and named!={item.nutrient_id}:
            return '원문의 성분명과 계산용 영양소 ID가 일치하지 않습니다. 성분명을 다시 확인해주세요.'
    own=aliases(item)
    if not own:return '항목명을 원문에서 확인할 수 없습니다.'
    owners=list(re.finditer('|'.join('(?:'+p+')' for p in own),question,re.I))
    if not owners:return '해당 음식/성분의 이름과 수치를 함께 다시 입력해주세요.'
    # Never borrow a number from a later nutrient, another item, or profile field.
    other=[p for x in all_items if x is not item for p in aliases(x)]
    foreign='|'.join([r'체중|몸무게|신장|나이',*(p for key in (*NUTRIENTS,*VITAMINS) for p in nutrient_aliases(key))])
    boundaries=list(re.finditer('|'.join([foreign,*other]),question,re.I))
    matches=[]
    for owner in owners:
        stop=min([m.start() for m in boundaries if m.start()>=owner.end()]+[m.start() for m in owners if m.start()>=owner.end()]+[len(question)])
        segment=question[owner.end():stop]
        quantities=quantities_in(segment,quantity_pattern,canonical_unit)
        end=re.search(r'먹었|마셨|섭취했|복용했|(?<!\d)[.!?]|[.!?](?!\d)',segment)
        if end:
            later=[q for q in quantities if q[2]>=end.start()]
            tail=segment[end.end():]
            # A subsequent reference question is not another intake quantity.
            reference_only=(later and all(q[1] not in COUNT_UNITS for q in later)
                            and re.search(r'기준|권고|상한|\bUL\b',tail,re.I)
                            and not re.search(r'먹|마셨|마신|섭취|복용',tail))
            if reference_only:
                quantities=[q for q in quantities if q[2]<end.start()]
            elif later and (any(q[1] not in COUNT_UNITS for q in later) or
                            not count_tail_is_clear(segment,end.start(),later)):
                return '뒤 문장의 수치가 같은 항목의 개수인지 불명확합니다. 항목명·개당 함량·실제 개수를 함께 입력해주세요.'
        # Do not search arbitrary later quantities for one matching the model.
        # An unknown/omitted food still leaves an extra mass/volume in this span.
        amounts=[q for q in quantities if q[1] not in COUNT_UNITS]
        if len(amounts)>1:
            return '한 항목 구간에 여러 함량이 있어 연결을 확정할 수 없습니다. 음식/성분을 빠짐없이 한 항목씩 입력해주세요.'
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
