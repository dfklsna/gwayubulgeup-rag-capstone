import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import capstone_compare as b

class RelationshipGroundingTests(unittest.TestCase):
    def check(self,q,**kwargs):
        data=dict(kind='nutrient',name='비타민 C',nutrient_id='vitamin_c',amount=500,unit='mg',count=1,evidence=q,intent='reported')
        data.update(kwargs)
        return b.validate_extraction(q,b.ExtractedRequest(items=[b.ExtractedIntake(**data)]))

    def test_default_one_cannot_drop_explicit_count(self):
        q='비타민 C 500mg 2정 먹었어.'
        self.assertFalse(self.check(q,count=1).items)
        self.assertEqual(self.check(q,count=2).items[0].count,2)

    def test_body_weight_cannot_be_food_amount(self):
        q='체중 70kg이고 파김치 150g 먹었어.'
        wrong=self.check(q,kind='food',name='파김치',nutrient_id=None,amount=70,unit='kg')
        right=self.check(q,kind='food',name='파김치',nutrient_id=None,amount=150,unit='g')
        self.assertFalse(wrong.items)
        self.assertEqual(right.items[0].amount,150)

    def test_later_item_quantity_cannot_be_borrowed(self):
        q='비타민 C 500mg 먹었고 비타민 D 25ug 먹었어.'
        self.assertFalse(self.check(q,amount=25,unit='ug').items)
        self.assertTrue(self.check(q).items)

    def test_explicit_total_not_multiplied_again(self):
        q='비타민 C 총 1000mg을 2정으로 먹었어.'
        self.assertTrue(self.check(q,amount=1000,count=1).items)
        self.assertFalse(self.check(q,amount=1000,count=2).items)

    def test_per_unit_label_and_korean_count(self):
        q='비타민 C 한 정당 500mg인 것을 두 정 먹었어.'
        self.assertTrue(self.check(q,count=2).items)
        self.assertFalse(self.check(q,count=1).items)

    def test_food_count_as_amount_is_not_multiplied_again(self):
        q='커피 두 잔 마셨어.'
        self.assertTrue(self.check(q,kind='food',name='커피',nutrient_id=None,amount=2,unit='잔',count=1).items)
        self.assertFalse(self.check(q,kind='food',name='커피',nutrient_id=None,amount=2,unit='잔',count=2).items)

    def test_nutrient_name_cannot_authorize_another_id(self):
        q='비타민 C 500mg 먹었어.'
        for name in ['비타민 C','비타민 B6','영양제']:
            self.assertFalse(self.check(q,name=name,nutrient_id='vitamin_b6').items)
        self.assertTrue(self.check(q).items)

    def test_conflicting_name_rejected_even_if_both_ids_in_question(self):
        q='비타민 C 500mg과 비타민 B6 500mg 먹었어.'
        self.assertFalse(self.check(q,nutrient_id='vitamin_b6').items)

    def test_omitted_food_cannot_supply_quantity(self):
        q='식품코드 D315-683000000-0001 파김치 150g과 해파리냉채 400g 먹었어.'
        for amount in [150,400]:
            self.assertFalse(self.check(q,kind='food',name='파김치',food_code='D315-683000000-0001',nutrient_id=None,amount=amount,unit='g').items)
        # The ambiguity guard is independent of a fixed dictionary of foods.
        q='파김치 150g과 낯선음식 400g 먹었어.'
        self.assertFalse(self.check(q,kind='food',name='파김치',nutrient_id=None,amount=400,unit='g').items)

    def test_omitted_mineral_cannot_supply_quantity(self):
        q='비타민 C 500mg과 철 10mg 먹었어.'
        self.assertFalse(self.check(q,amount=10).items)

    def test_count_continuation_after_consumption(self):
        for tail in ['총 2정이야.','두 정이야.','총 2정이야. 상한 기준과 비교해줘.']:
            q='비타민 C 한 정당 500mg짜리를 먹었어. '+tail
            self.assertFalse(self.check(q,count=1).items)
            self.assertTrue(self.check(q,count=2).items)

    def test_ambiguous_or_unrelated_count_is_not_assigned(self):
        for tail in ['다른 약 2정도 먹었어.','2정이 아니라 3정이야.']:
            q='비타민 C 500mg 먹었어. '+tail
            for count in [1,2,3]:self.assertFalse(self.check(q,count=count).items)

    def test_reference_value_after_intake_cannot_replace_amount(self):
        q='수유 중이고 카페인 120mg 먹었어. 일반 성인 400mg 기준으로 비교해줘.'
        self.assertTrue(self.check(q,name='카페인',nutrient_id='caffeine',amount=120).items)
        self.assertFalse(self.check(q,name='카페인',nutrient_id='caffeine',amount=400).items)

    def test_bad_model_output_blocked_through_parse_and_calculate(self):
        from unittest.mock import Mock,patch
        from types import SimpleNamespace
        q='비타민 C 500mg 먹었어.'
        raw=b.ExtractedRequest(items=[b.ExtractedIntake(kind='nutrient',name='비타민 C',nutrient_id='vitamin_b6',amount=500,unit='mg',evidence=q,intent='reported')])
        api=Mock();api.responses.parse.return_value=SimpleNamespace(output_parsed=raw)
        with patch.object(b,'client',return_value=api):request=b.parse_question(q)
        result=b.calculate(request)
        self.assertEqual(api.responses.parse.call_count,2)
        self.assertEqual(result['status'],'needs_clarification')
        self.assertEqual(result['items'],[])

if __name__=='__main__':unittest.main()
