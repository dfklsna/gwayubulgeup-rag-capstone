import sys
from pathlib import Path
import unittest
import os
import tempfile
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import experiments as e
import capstone_compare as b


class ExperimentTests(unittest.TestCase):
    def test_empty_env_template_does_not_erase_explicit_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('RAG_DATA_DIR=\nOPENAI_API_KEY=local-test-placeholder\n')
            with patch.dict(os.environ,{'RAG_DATA_DIR':'data/demo','OPENAI_API_KEY':'old-test-placeholder'}):
                b.load_local_settings(path)
                self.assertEqual(os.environ['RAG_DATA_DIR'],'data/demo')
                self.assertEqual(os.environ['OPENAI_API_KEY'],'local-test-placeholder')

    def test_variants_change_one_component(self):
        default=e.asdict(e.Strategy())
        for variant in e.VARIANTS:
            value=e.asdict(e.strategy_for(variant))
            self.assertEqual(sum(value[k]!=default[k] for k in value),1)

    def test_bm25_retrieves_korean_inflected_term(self):
        scores=e.BM25(['카페인 최대 섭취 안내','칼슘 섭취 안내']).scores('카페인은?')
        self.assertGreater(scores[0],scores[1])

    def test_rrf_combines_rank_not_score_scale(self):
        rank,_=e.rrf([[0,1,2],[2,1,3]])
        self.assertEqual(rank[0],2)
        self.assertIn(3,rank)

    def test_mmr_can_select_diverse_candidate(self):
        vectors=np.array([[1,0],[1,0],[0,1]],dtype='float32')
        result=e.mmr_select([0,1,2],vectors,np.array([1,.99,.8]),2,weight=.5)
        self.assertEqual(result,[0,2])

    def test_combined_citation_range_checked_and_repaired(self):
        hits=[{'citation':'D1'},{'citation':'D2'}]
        text='자료 [T1, D1~D3]'
        audit=e.citation_audit(text,hits,{'items':[],'clarifications':[]})
        self.assertEqual(audit['unknown_ids'],['D3','T1'])
        self.assertEqual(e.repair_citations(text,hits,{'items':[]}),'자료 [D1][D2]')
        self.assertEqual(e.citation_audit('[T1]',[],{'items':[],'clarifications':['섭취량 필요']})['unknown_ids'],[])

    def test_citation_repair_does_not_rewrite_claim(self):
        self.assertEqual(e.repair_citations('근거 없는 주장 [T99]',[],{'items':[]}),'근거 없는 주장 ')

    def test_round_parentheses_citations(self):
        hits=[{'citation':'D1'}]
        text='제공된 자료(T1, D1~D3)에 없는 제품입니다.'
        self.assertEqual(e.citation_audit(text,hits,{'items':[]})['unknown_ids'],['D2','D3','T1'])
        self.assertEqual(e.repair_citations(text,hits,{'items':[]}),'제공된 자료[D1]에 없는 제품입니다.')

    def test_guard_does_not_estimate_cup_content(self):
        request=b.Request(question='커피 3잔',items=[b.Intake(kind='food',name='커피',amount=3,unit='잔')])
        text=e.guarded_answer(b.calculate(request))
        self.assertIn('추정하지 않습니다',text)
        self.assertNotIn('mg',text)

    def test_guard_rni_is_not_rendered_as_excess(self):
        tools={'items':[{'reported_amount':'300','unit':'mg','comparisons':[{'status':'adequacy_reference_only_not_an_excess_limit','reference_type':'RNI','value':100}]}],'clarifications':[]}
        text=e.guarded_answer(tools)
        self.assertNotIn('기준을 초과합니다',text)

    def test_guard_strict_upper_bound_in_max_column(self):
        tools={'items':[{'reported_amount':'300','unit':'mg','comparisons':[{'nutrient_name':'가상 성분','status':'above_recommendation_for_reported_intake','reference_type':'recommendation','reference_value':None,'reference_max':300,'reference_unit':'mg','reference_comparator':'lt'}]}],'clarifications':[]}
        text=e.guarded_answer(tools)
        self.assertIn('300mg/일 미만',text)
        self.assertIn('미만 조건을 충족하지 않습니다',text)

    def test_compression_retains_scope_and_numbers(self):
        tools={'items':[{'comparisons':[{'status':'requires_form_scope_or_additional_data','value':3000,'source':{'url':'test'}},{'status':'not_established_in_table','value':None}]}],'clarifications':['형태 필요']}
        compact=e.compact_tools(tools)
        row=compact['items'][0]['comparisons'][0]
        self.assertEqual(row['value'],3000)
        self.assertEqual(row['status'],'requires_form_scope_or_additional_data')
        self.assertEqual(compact['source_registry'][row['source']],{'url':'test'})
        self.assertEqual(compact['clarifications'],['형태 필요'])
        self.assertEqual(len(tools['items'][0]['comparisons']),2)

    def test_extract_keeps_source_identity_and_verbatim_text(self):
        hit={'citation':'D2','document_id':'test','text':'칼슘 안내.\n\n카페인 조건 안내.','pdf_page':5}
        result=e.extract_context('카페인',hit,limit=10)
        self.assertEqual(result['citation'],'D2')
        self.assertEqual(result['pdf_page'],5)
        self.assertIn(result['text'],hit['text'])


if __name__=='__main__':unittest.main()
