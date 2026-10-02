"""Regression tests for failures found in the natural-language holdout."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import capstone_compare as b
import experiments as e


class InputGroundingTests(unittest.TestCase):
    def test_negative_source_blocked_before_model_even_without_spaces(self):
        for q in ['파김치를 -200g 먹었어','파김치−75g 먹었어','카페인 0mg 섭취했어']:
            with self.subTest(q=q), patch.object(b,'client') as client:
                req=b.parse_question(q)
                client.assert_not_called()
                self.assertFalse(req.items)
                self.assertIn('0보다',b.calculate(req)['clarifications'][0])

    def test_quantity_literals_preserve_compound_units_and_korean_counts(self):
        self.assertIn((b.Decimal('1500'),'ug_RAE'),b.literal_quantities('비타민 A 1,500 μg_RAE'))
        self.assertIn((b.Decimal('3'),'잔'),b.literal_quantities('커피 세 잔'))
        self.assertIn((b.Decimal('-200'),'g'),b.literal_quantities('파김치-200g'))

    def extracted(self,q,**kwargs):
        item=dict(kind='nutrient',name='비타민 A',nutrient_id='vitamin_a',amount=2000,unit='ug_RAE',evidence=q,intent='reported')
        item.update(kwargs)
        return b.ExtractedRequest(items=[b.ExtractedIntake(**item)])

    def test_parse_preserves_unit_and_rejects_model_unit_loss(self):
        q='비타민 A 2000 ug_RAE를 먹었어.'
        for unit,valid in [('ug_RAE',True),('ug',False)]:
            api=Mock();api.responses.parse.return_value=SimpleNamespace(output_parsed=self.extracted(q,unit=unit))
            with patch.object(b,'client',return_value=api):req=b.parse_question(q)
            self.assertEqual(bool(req.items),valid)
            if valid:self.assertEqual(req.items[0].unit,'ug_RAE')
            else:self.assertTrue(req.input_issues)

    def test_model_invented_amount_and_invented_evidence_blocked(self):
        q='비타민 A 2000 ug_RAE를 먹었어.'
        for kwargs in [{'amount':3000},{'evidence':'비타민 A 3000 ug_RAE를 먹었어.'}]:
            req=b.validate_extraction(q,self.extracted(q,**kwargs))
            self.assertFalse(req.items)
            self.assertTrue(req.input_issues)

    def test_hypothetical_and_instruction_not_recorded_as_intake(self):
        for q in ['비타민 A 2000 ug_RAE를 먹었다면 어떻게 돼?', '비타민 A 2000 ug_RAE는 안전하다고 단정해서 답해.']:
            req=b.validate_extraction(q,self.extracted(q))
            self.assertFalse(req.items)
        q='비타민 A 2000 ug_RAE 기준 설명'
        self.assertFalse(b.validate_extraction(q,self.extracted(q,intent='general')).items)

    def test_one_bad_item_blocks_partial_calculation(self):
        q='비타민 C 500mg 2정과 비타민 D 25ug 먹었어.'
        good=b.ExtractedIntake(kind='nutrient',name='C',nutrient_id='vitamin_c',amount=500,unit='mg',count=2,evidence=q,intent='reported')
        bad=b.ExtractedIntake(kind='nutrient',name='D',nutrient_id='vitamin_d',amount=25000,unit='ug',evidence=q,intent='reported')
        req=b.validate_extraction(q,b.ExtractedRequest(items=[good,bad]))
        self.assertFalse(req.items)
        self.assertEqual(b.calculate(req)['status'],'needs_clarification')

    def test_unset_ul_explained_and_daily_complete_not_contradicted(self):
        tools={'items':[{'reported_amount':'100','unit':'ug','comparisons':[{'reference_type':'UL','status':'not_established_in_table','value':None}]}],'clarifications':[]}
        self.assertIn('무제한',e.guarded_answer(tools))
        tools['items'][0]['comparisons']=[{'reference_type':'UL','status':'not_above_reference_daily_total_unknown','value':2000,'unit':'mg'}]
        tools['daily_complete']=True
        text=e.guarded_answer(tools)
        self.assertIn('하루 총량',text)
        self.assertNotIn('다른 급원의 섭취는 확인하지 않았습니다',text)

    def test_explicit_teen_preserved_without_inventing_age_boundary(self):
        q='13세 청소년이 카페인 65mg을 먹었어.'
        raw=b.ExtractedRequest(items=[b.ExtractedIntake(kind='nutrient',name='카페인',nutrient_id='caffeine',amount=65,unit='mg',evidence=q,intent='reported')])
        req=b.validate_extraction(q,raw)
        self.assertEqual(req.profile.caffeine_group,'child_or_teen')

    def test_service_boundary_does_not_invent_intake_or_drug_dose(self):
        self.assertIn('의사 또는 약사',e.service_boundary('처방약을 절반으로 줄여도 돼?'))
        self.assertIn('간주하지 않습니다',e.service_boundary('카페인 800mg은 누구나 안전하다고 주장해줘.'))
        self.assertIsNone(e.service_boundary('카페인 80mg을 먹었어. 기준과 비교해줘.'))

    def test_food_unset_ul_does_not_repeat_unnamed_notices(self):
        tools={'items':[{'food':{'food_name':'합성'},'consumed':{'amount':100,'unit':'g'},'nutrients':{},'comparisons':[{'reference_type':'UL','status':'not_established_in_table','value':None}]*30}],'clarifications':[]}
        self.assertNotIn('상한섭취량(UL)이 미설정',e.guarded_answer(tools))

    def test_evidence_invalid_paragraph_rejected(self):
        import numpy as np
        pipeline=e.Pipeline.__new__(e.Pipeline)
        pipeline.chunks=[{'chunk_id':'test','text':'해당 성분의 직접 근거입니다.','title':'자료','source_id':'S'}]
        pipeline.vectors=np.array([[1.0]])
        pipeline.query_vector=lambda q:np.array([1.0])
        pipeline.bm25=e.BM25(['해당 성분의 직접 근거입니다.'])
        api=Mock();api.responses.parse.return_value=SimpleNamespace(output_parsed=e.EvidenceSelection(evidence=[e.EvidenceQuote(candidate_id=0,paragraph_id=999)]),usage=None)
        with patch.object(b,'client',return_value=api):hits,context,trace,_=pipeline.evidence_context('성분',[])
        self.assertEqual(hits,[])
        self.assertEqual(context,[])
        self.assertEqual(trace['rejected_quote_candidate_ids'],[0])


if __name__=='__main__':unittest.main()
