"""Adversarial extraction regressions plus supported-input controls."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import capstone_compare as b


class ContextGroundingTests(unittest.TestCase):
    def request(self,q,profile=None,daily=False,**fields):
        item=dict(kind='nutrient',name='비타민 C',nutrient_id='vitamin_c',amount=500,unit='mg',evidence=q,intent='reported')
        item.update(fields)
        return b.ExtractedRequest(profile=b.Profile(**(profile or {})),daily_complete=daily,items=[b.ExtractedIntake(**item)])

    def check(self,q,valid,**fields):
        result=b.validate_extraction(q,self.request(q,**fields))
        self.assertEqual(bool(result.items),valid,(q,result.input_issues))
        if not valid:self.assertEqual(b.calculate(result)['status'],'needs_clarification')
        return result

    def test_invented_profile_fields_blocked(self):
        for field,value in [('age_years',30),('sex','female'),('weight_kg',70),('life_stage','general'),('caffeine_group','adult'),('trimester',2)]:
            with self.subTest(field=field):self.check('비타민 C 500mg 먹었어.',False,profile={field:value})

    def test_explicit_profile_preserved(self):
        q='30세 남성 일반 성인이고 체중은 70kg이야. 비타민 C 500mg 먹었어.'
        profile=dict(age_years=30,sex='male',life_stage='general',caffeine_group='adult',weight_kg=70)
        result=self.check(q,True,profile=profile)
        for field,value in profile.items():self.assertEqual(getattr(result.profile,field),value)

    def test_wrong_age_sex_weight_blocked(self):
        q='30세 남성 일반 성인이고 체중은 70kg이야. 비타민 C 500mg 먹었어.'
        for profile in [dict(age_years=31),dict(sex='female'),dict(weight_kg=50)]:self.check(q,False,profile=profile)

    def test_pregnancy_not_general(self):
        q='32세 여성이고 임신 중이야. 비타민 C 500mg 먹었어.'
        self.check(q,False,profile=dict(life_stage='general',caffeine_group='adult'))
        result=self.check(q,True,profile=dict(life_stage='pregnancy',caffeine_group='pregnancy'))
        self.assertEqual(result.profile.life_stage,'pregnancy')

    def test_missing_explicit_profile_is_restored_from_source(self):
        q='32세 여성이고 임신 중이야. 비타민 C 500mg 먹었어.'
        result=self.check(q,True)
        self.assertEqual(result.profile.life_stage,'pregnancy')
        self.assertEqual(result.profile.caffeine_group,'pregnancy')

    def test_lactation_not_reference_adult(self):
        q='30세 여성이고 아기에게 수유 중이야. 비타민 C 500mg 먹었어. 일반 성인 400mg 기준으로 비교해줘.'
        self.check(q,False,profile=dict(life_stage='general',caffeine_group='adult'))
        result=self.check(q,True,profile=dict(life_stage='lactation'))
        self.assertIsNone(result.profile.caffeine_group)

    def test_negated_pregnancy_not_positive(self):
        q='30세 여성이고 임신·수유 중이 아닌 일반 성인이야. 비타민 C 500mg 먹었어.'
        self.check(q,False,profile=dict(life_stage='pregnancy'))
        self.check(q,True,profile=dict(life_stage='general',caffeine_group='adult'))

    def test_reference_question_does_not_ground_profile(self):
        for context in ['30세 여성 기준으로 비교해줘.','일반 성인 기준이야.','30세 여성이야?','체중 70kg이라면 비교해줘.']:
            for profile in [dict(age_years=30),dict(sex='female'),dict(caffeine_group='adult'),dict(weight_kg=70)]:
                self.check('비타민 C 500mg 먹었어. '+context,False,profile=profile)

    def test_ambiguous_people_and_conflicting_profile_blocked(self):
        for context in ['나는 30세 남성이고 아내는 28세 여성이야.','30세 남성이야. 40세 남성이야.','남성이 아니야.']:
            self.check(context+' 비타민 C 500mg 먹었어.',False,profile=dict(age_years=30,sex='male'))

    def test_trimester_requires_explicit_current_value(self):
        q='32세 여성이고 임신 2분기야. 비타민 C 500mg 먹었어.'
        self.check(q,True,profile=dict(life_stage='pregnancy',trimester=2))
        self.check(q,False,profile=dict(life_stage='pregnancy',trimester=3))

    def test_mixed_count_omission_and_borrow_blocked(self):
        for other in ['커피 두 잔','다른 약 2정','영양제 2정','알수없는제품 세 캡슐']:
            for order in [f'비타민 C 500mg과 {other}',f'{other}과 비타민 C 500mg']:
                for count in [1,2,3]:self.check(order+' 먹었어.',False,count=count)

    def test_full_mass_and_count_items_preserved(self):
        q='비타민 C 500mg과 커피 두 잔 마셨어.'
        raw=self.request(q)
        raw.items.append(b.ExtractedIntake(kind='food',name='커피',amount=2,unit='잔',evidence=q,intent='reported'))
        result=b.validate_extraction(q,raw)
        self.assertEqual(len(result.items),2,result.input_issues)
        self.assertEqual(b.calculate(result)['status'],'needs_clarification')

    def test_common_verbs_detect_missing_items_in_both_orders(self):
        for verb in ['먹고 있어','복용 중이야','복용하고 있어','섭취하고 있어','먹음','복용함','섭취했어','마시고 있어']:
            for order in ['비타민 C 500mg과 비타민 D 25ug','비타민 D 25ug과 비타민 C 500mg']:
                self.check(order+' '+verb+'.',False)
                self.check('비타민 C 500mg '+verb+'.',True)

    def test_common_verbs_complete_pairs_preserved(self):
        for verb in ['먹고 있어','복용 중이야','먹음']:
            q='비타민 C 500mg과 비타민 D 25ug '+verb+'.'
            raw=self.request(q)
            raw.items.append(b.ExtractedIntake(kind='nutrient',name='비타민 D',nutrient_id='vitamin_d',amount=25,unit='ug',evidence=q,intent='reported'))
            self.assertEqual(len(b.validate_extraction(q,raw).items),2)

    def test_evidence_cannot_hide_hypothesis(self):
        q='가정: 비타민 C 500mg 먹었어. 어떻게 돼?'
        self.check(q,False,evidence='비타민 C 500mg 먹었어.')
        self.check(q,False)

    def test_evidence_requires_exact_whole_source(self):
        q='비타민 C 500mg 먹었어. 상한과 비교해줘.'
        self.check(q,False,evidence='비타민 C 500mg 먹었어.')
        self.check(q,True)

    def test_negated_or_conditional_intake_blocked(self):
        for q in ['비타민 C 500mg 복용했다면 어떻게 돼?','비타민 C 500mg 안 먹었어.','비타민 C 500mg 먹지 않았어.']:
            self.check(q,False)

    def test_daily_complete_requires_all_day_assertion(self):
        for q in ['오늘 비타민 C 500mg 먹었어.','비타민 C 총 500mg 먹었어.','비타민 C 500mg 먹었어. 오늘 먹은 전부가 아니야.']:
            self.assertFalse(self.check(q,True,daily=True).daily_complete)
        q='비타민 C 500mg 먹었어. 오늘 하루 먹은 전부야.'
        for daily in [False,True]:self.assertTrue(self.check(q,True,daily=daily).daily_complete)

    def test_daily_complete_questions_future_and_hypotheses_not_promoted(self):
        from input_grounding import grounded_daily_complete
        for tail in ['오늘 하루 먹은 전부야?','내일 하루 먹은 전부야.','가정: 오늘 하루 먹은 전부야.','오늘 하루 먹은 전부는 아니야.']:
            self.assertFalse(grounded_daily_complete(tail))

    def test_bad_profile_and_count_blocked_through_parse_calculate(self):
        for q,kwargs in [('비타민 C 500mg 먹었어.',dict(profile=dict(age_years=30))),('비타민 C 500mg과 커피 두 잔 마셨어.',dict(count=2))]:
            api=Mock();api.responses.parse.return_value=SimpleNamespace(output_parsed=self.request(q,**kwargs))
            with patch.object(b,'client',return_value=api):request=b.parse_question(q)
            self.assertEqual(api.responses.parse.call_count,2)
            self.assertEqual(b.calculate(request)['status'],'needs_clarification')
            self.assertEqual(b.calculate(request)['items'],[])

    def test_schema_cannot_generate_partial_evidence_or_invented_profile(self):
        from pydantic import ValidationError
        q='16세 청소년이고 체중은 50kg이야. 비타민 C 500mg 먹었어.'
        schema=b.extraction_schema(q)
        raw=self.request(q).model_dump()
        schema.model_validate(raw)
        raw['items'][0]['evidence']='비타민 C 500mg 먹었어.'
        with self.assertRaises(ValidationError):schema.model_validate(raw)
        raw=self.request(q,profile=dict(life_stage='general')).model_dump()
        with self.assertRaises(ValidationError):schema.model_validate(raw)
        raw=self.request(q,profile=dict(age_years=16,weight_kg=50,caffeine_group='child_or_teen')).model_dump()
        schema.model_validate(raw)

    def test_food_ramen_not_profile_conditional(self):
        q='30세 남성 일반 성인이야. 라면 500g 먹었어.'
        result=self.check(q,True,kind='food',name='라면',nutrient_id=None,unit='g',profile=dict(age_years=30,sex='male',life_stage='general',caffeine_group='adult'))
        self.assertEqual(result.profile.age_years,30)

    def test_weight_question_is_not_profile_assertion(self):
        self.check('체중은 70kg이야? 비타민 C 500mg 먹었어.',False,profile=dict(weight_kg=70))

    def test_named_supplement_count_link_without_conjunction(self):
        self.check('비타민 C 500mg짜리 영양제 두 정 먹었어.',True,count=2)
        self.check('비타민 C 500mg과 영양제 두 정 먹었어.',False,count=2)

    def test_source_profile_ranges_do_not_crash_or_choose_thresholds(self):
        for header in ['130세 남성이야.','체중은 0kg이야.','체중은 501kg이야.']:
            q=header+' 비타민 C 500mg 먹었어.'
            self.check(q,False)
            b.extraction_schema(q)  # Invalid literals must not enter the schema.

    def test_profile_words_in_product_or_reference_are_not_identity(self):
        for header,profile in [('남성용 제품이야.',dict(sex='male')),('참고: 30세 남성 일반 성인이야.',dict(age_years=30)),('미성인이야.',dict(caffeine_group='adult'))]:
            self.check(header+' 비타민 C 500mg 먹었어.',False,profile=profile)

    def test_coffee_label_and_vitamin_pair_preserved(self):
        q='한 잔당 카페인 100mg인 커피 2잔과 비타민 C 500mg짜리 2정을 먹었어. 두 항목을 같이 분석해줘.'
        raw=self.request(q,count=2)
        raw.items.append(b.ExtractedIntake(kind='nutrient',name='카페인',nutrient_id='caffeine',amount=100,unit='mg',count=2,evidence=q,intent='reported'))
        result=b.validate_extraction(q,raw)
        self.assertEqual(len(result.items),2,result.input_issues)
        self.assertIn('합산',b.calculate(result)['clarifications'][0])
        self.check('비타민 C 500mg과 커피 두 잔 마셨어.',False,count=2)

if __name__=='__main__':unittest.main()
