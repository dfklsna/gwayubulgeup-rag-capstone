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

if __name__=='__main__':unittest.main()
