"""Conservative item-to-quantity binding for supported intake expressions.

Unclear ownership is rejected, not repaired. This is not a general Korean parser.
"""
from decimal import Decimal
import re

COUNTS={'한':1,'두':2,'세':3,'네':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9,'열':10}
COUNT_UNITS={'캡슐','인분','잔','정','개','캔'}
INTAKE_VERB=r'(?:먹었|마셨|섭취했|복용했|먹고\s*있|마시고\s*있|(?:섭취|복용)하고\s*있|(?:섭취|복용)\s*중|먹음|마심|섭취함|복용함)'
NON_REPORT=r'가정|예를\s*들|(?:먹|마시|섭취하|복용하)면|(?:먹었|마셨|섭취했|복용했)(?:다)?면|(?:먹|마시|섭취하|복용하)지\s*않|안\s*(?:먹|마시|섭취|복용)|단정해서|출처를\s*만들'


def count_link_is_clear(text):
    """Allow direct dose/label links, never a conjunction to another item."""
    return re.fullmatch(r'(?:(?:짜리|이라고|라고|표시된|적힌|커피|음료|제품|영양제|보충제|인|것|을|를|으로|은|는|의|에|당|총|실제로)|\s)*',text) is not None


def validate_profile_grounding(question, profile):
    """Return explicitly stated profile facts and issues; never infer age cutoffs.

    Only declarative profile phrases are supported. Reference questions, ambiguous
    people, negations and conditions cannot authorize comparator inputs.
    """
    facts={key:set() for key in profile.model_dump()}
    issues=[]
    # Multiple people/corrections require clarification rather than choosing one.
    ambiguous=bool(re.search(r'친구|아내|남편|아들|딸|동생|엄마|아빠|아니라|가정|이라면|다면',question))
    statements=[]
    for sentence in re.finditer(r'(?:[^.!?\n]|(?<=\d)\.(?=\d))+[.!?]?',question):
        clause=sentence.group()
        if clause.endswith('?'):continue
        # A reference noun alone ("일반 성인 400mg 기준") is not a profile.
        declarative=list(re.finditer(r'이야|이고|입니다|이에요|인데|이(?:다|며)|청소년이\s|(?:분기|세|살)야',clause))
        if declarative:
            statement=clause[:declarative[-1].end()]
            if not re.search(r'기준|권고|예시|예를|참고|경우|대상|라고|이라면|다면',statement):
                statements.append(statement)
    text=' '.join(statements)
    for m in re.finditer(r'(?<![\d.])(?:만\s*)?(\d{1,3}(?:\.\d+)?)\s*(?:세|살)',text):
        facts['age_years'].add(float(m.group(1)))
    for word,value in [('남성','male'),('남자','male'),('여성','female'),('여자','female')]:
        if re.search(word+r'(?=\s|이고|이야|입니다|이에요|인데|이다|[,.]|$)',text) and not re.search(word+r'.{0,8}(?:아닌|아니|않)',text):facts['sex'].add(value)
    for m in re.finditer(r'(?:체중|몸무게)(?:은|는|이|가|:|\s)*(\d+(?:\.\d+)?)\s*kg',text,re.I):
        if re.match(r'\s*(?:이야|이고|입니다|이에요|인데|이다|이\s)',text[m.end():]):
            facts['weight_kg'].add(float(m.group(1)))
    # Remove the complete paired negation, not just one of its life stages.
    clean=re.sub(r'임신\s*[·/및과\s]+수유\s*(?:중이\s*)?(?:아닌|아니|않)[^,.!?]*?(?=일반|$)','',text)
    for word,value in [('임신','pregnancy'),('수유','lactation')]:
        if re.search(word+r'\s*(?:중|상태)',clean) and not re.search(word+r'.{0,10}(?:않|아니|아닌)',clean):
            facts['life_stage'].add(value)
    if re.search(r'일반\s*성인',clean):facts['life_stage'].add('general')
    if re.search(r'청소년|어린이',clean):facts['caffeine_group'].add('child_or_teen')
    if re.search(r'(?<![가-힣])성인(?=\s|이고|이야|입니다|이에요|인데|이다|$)',clean):facts['caffeine_group'].add('adult')
    # Pregnancy is an explicit caffeine category; lactation is not adult.
    if facts['life_stage']=={'pregnancy'}:facts['caffeine_group']={'pregnancy'}
    if facts['life_stage']=={'lactation'}:facts['caffeine_group']=set()
    for m in re.finditer(r'임신\s*([123])\s*(?:분기|삼분기)',text):
        facts['trimester'].add(int(m.group(1)))
        facts['life_stage'].add('pregnancy')
        facts['caffeine_group']={'pregnancy'}
    grounded={}
    for key,low,high in [('age_years',0,120),('weight_kg',0,500)]:
        if any(value<low or value>high or key=='weight_kg' and value==0 for value in facts[key]):
            issues.append('프로필 '+key+' 값이 지원 범위를 벗어났습니다. 현재 조건을 확인해주세요.')
            facts[key]=set()
    for key,value in profile.model_dump().items():
        allowed=facts[key] if not ambiguous else set()
        if len(allowed)>1 or value is not None and value not in allowed:
            issues.append('프로필 '+key+' 값이 원문의 명시적 조건과 일치하지 않습니다. 나이·성별·생애 상태·체중을 한 사람 기준으로 알려주세요.')
        grounded[key]=next(iter(allowed)) if len(allowed)==1 else None
    # A negative/conditional assertion must never be promoted to a positive fact.
    if re.search(r'아닌|아니|않|이라면|다면',clean):
        if any(value is not None for value in grounded.values()):
            issues.append('부정·조건이 포함된 프로필은 자동 확정하지 않습니다. 현재 조건을 별도로 알려주세요.')
            grounded={key:None for key in grounded}
    # Check cross-field consistency before rebuilding the validated Profile.
    if grounded['sex']=='male' and grounded['life_stage'] in ('pregnancy','lactation'):
        issues.append('프로필의 성별과 생애 상태가 서로 맞지 않습니다.')
        grounded={key:None for key in grounded}
    return grounded,issues


def grounded_daily_complete(question):
    """Only an explicit all-day completeness assertion authorizes True."""
    if re.search(NON_REPORT+r'|아니|않|내일|예정|일까|인가|맞아|\?',question):return False
    return bool(re.search(r'(?:오늘|하루)(?:\s*하루)?\s*(?:동안\s*)?(?:먹은|마신|섭취한|복용한)(?:\s*것(?:은|이)?)?\s*(?:전부|모두|전체)(?:야|다|입니다|예요|이야|이다)',question)
                or re.search(r'(?:이게|이것이|이것은)\s*(?:오늘|하루)(?:\s*하루)?\s*(?:섭취량|먹은\s*것)의?\s*(?:전부|전체)(?:야|다|입니다|예요|이야|이다)',question))
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
    events=re.finditer(INTAKE_VERB+r'|(?<!\d)[.!?]|[.!?](?!\d)|[;\n]',question)
    for event in events:
        if not re.fullmatch(INTAKE_VERB,event.group()):
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
        for q in quantities:
            if q[1] in COUNT_UNITS and mass:
                # Per-unit label or a locally attached count is accounted for by
                # bound_issue. An independent count-only item must still match.
                before=[m for m in mass if m[3]<=q[2]]
                if re.match(r'\s*당',segment[q[3]:]) or (before and count_link_is_clear(segment[before[-1][3]:q[2]])):
                    continue
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
        end=re.search(INTAKE_VERB+r'|(?<!\d)[.!?]|[.!?](?!\d)',segment)
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
            for q in quantities:
                if q[1] in COUNT_UNITS and q[2]>chosen[3] and not re.match(r'\s*당',segment[q[3]:]):
                    link=segment[chosen[3]:q[2]]
                    if not count_link_is_clear(link) and not (end and q[2]>=end.start() and count_tail_is_clear(segment,end.start(),[q])):
                        return '같은 문장의 개수가 다른 항목에 연결될 수 있습니다. 항목별 함량과 실제 개수를 분리해주세요.'
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
