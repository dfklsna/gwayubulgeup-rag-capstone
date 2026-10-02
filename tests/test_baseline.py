"""Deterministic boundary tests; external corpus tests skip on a public clean clone."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import capstone_compare as rag


class BaselineTests(unittest.TestCase):
    def test_mass_volume_guard(self):
        record={'basis':{'amount':100,'unit':'ml'}}
        with self.assertRaisesRegex(ValueError,'밀도'):
            rag.food_tools.scale_food(record,400,'g')

    def test_negative_or_nonfinite_intake_rejected(self):
        for amount in [-1,0,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):
                rag.Intake(kind='food',name='test',amount=amount,unit='g')

    def test_pages_preserved(self):
        chunks=rag.split_documents([{'document_id':'test','source_id':'x','title':'test','text':'[PDF page 1]\n첫 장\n[PDF page 3]\n셋째 장'}])
        self.assertEqual([c['pdf_page'] for c in chunks],[1,3])
        self.assertEqual(len({c['chunk_id'] for c in chunks}),2)

    def test_exclude_historical(self):
        self.assertEqual(rag.split_documents([{'preferred_for_baseline':False}]),[])

    def test_cups_without_strength_requests_clarification(self):
        result=rag.calculate(rag.Request(question='커피 2잔 먹었어',items=[rag.Intake(kind='food',name='커피',amount=2,unit='잔')]))
        self.assertEqual(result['status'],'needs_clarification')
        self.assertEqual(result['items'],[])

    def test_multiple_items_not_silently_dropped(self):
        item=rag.Intake(kind='nutrient',name='카페인',nutrient_id='caffeine',amount=100,unit='mg')
        result=rag.calculate(rag.Request(question='둘을 합쳐줘',items=[item,item]))
        self.assertEqual(result['status'],'needs_clarification')
        self.assertEqual(result['items'],[])

    def test_no_fabricated_amount(self):
        result=rag.calculate(rag.Request(question='커피 2잔',items=[rag.Intake(kind='food',name='커피')]))
        self.assertEqual(result['status'],'needs_clarification')
        self.assertEqual(result['items'],[])

    def test_caffeine_boundaries_and_body_weight(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            rules={g:{'value':v,'source':{'source_id':'test'}} for g,v in [('adult',400),('pregnancy',300),('child_or_teen',2.5)]}
            (p/'caffeine_rules.json').write_text(json.dumps(rules))
            with patch.object(rag,'DATA',p):
                adult=rag.Profile(life_stage='general',caffeine_group='adult')
                self.assertEqual(rag.caffeine_check(400,adult)['status'],'not_above_recommendation_daily_total_unknown')
                self.assertEqual(rag.caffeine_check(401,adult)['status'],'above_recommendation_for_reported_intake')
                child=rag.Profile(caffeine_group='child_or_teen')
                self.assertEqual(rag.caffeine_check(100,child)['status'],'needs_clarification')
                child.weight_kg=40
                self.assertEqual(rag.caffeine_check(100,child)['reference_mg'],'100.0')
                pregnancy=rag.Profile(life_stage='pregnancy')
                self.assertEqual(rag.caffeine_check(301,pregnancy)['reference_mg'],'300')
                self.assertEqual(rag.caffeine_check(100,rag.Profile(life_stage='lactation'))['status'],'requires_individual_guidance')

    def test_rni_is_not_an_upper_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            (p/'nutrient_reference_definitions.json').write_text(json.dumps([{'nutrient_id':'vitamin_c','unit':'mg'}]))
            refs=[{'reference_id':'test','reference_type':kind,'status':'numeric','value':amount,'unit':'mg','intake_scope':'total_intake','source':{},'comparator':'reference'} for kind,amount in [('RNI',100),('UL',2000)]]
            with patch.object(rag,'DATA',p),patch.object(rag.ref_tools,'reference_lookup',return_value=refs):
                i=rag.Intake(kind='nutrient',name='C',nutrient_id='vitamin_c',amount=2000,unit='mg')
                result=rag.nutrient_check(i,rag.Profile(age_years=30,sex='male',life_stage='general'))
                self.assertEqual(result['comparisons'][0]['status'],'adequacy_reference_only_not_an_excess_limit')
                self.assertEqual(result['comparisons'][1]['status'],'not_above_reference_daily_total_unknown')

    def test_iu_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            (p/'nutrient_reference_definitions.json').write_text(json.dumps([{'nutrient_id':'vitamin_d','unit':'ug'}]))
            with patch.object(rag,'DATA',p):
                with self.assertRaisesRegex(ValueError,'IU'):
                    rag.nutrient_check(rag.Intake(kind='nutrient',name='D',nutrient_id='vitamin_d',amount=1000,unit='IU'),rag.Profile())


@unittest.skipUnless((ROOT/'data/prepared/foods.sqlite').exists(),'Full third-party corpus not present')
class LocalCorpusTests(unittest.TestCase):
    def test_jellyfish_golden(self):
        result=rag.calculate(rag.Request.model_validate_json((ROOT/'examples/jellyfish_400g.json').read_text()))
        item=result['items'][0]
        self.assertEqual(item['nutrients']['나트륨']['amount'],'1356.0')
        self.assertEqual(item['nutrients']['에너지']['amount'],'244.0')
        sodium=next(r for r in item['comparisons'] if r['nutrient_id']=='sodium' and r['reference_type']=='CDRR')
        self.assertEqual(sodium['status'],'not_above_reference_for_this_food_daily_total_unknown')

    def test_same_name_needs_choice(self):
        result=rag.calculate(rag.Request(question='해파리냉채 400g',items=[rag.Intake(kind='food',name='해파리냉채',amount=400,unit='g')]))
        self.assertEqual(result['status'],'needs_clarification')
        self.assertEqual(len(result['items'][0]['candidates']),4)


if __name__=='__main__':unittest.main()
