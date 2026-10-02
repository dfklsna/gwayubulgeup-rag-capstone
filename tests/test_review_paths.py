"""Execute reviewed branches with synthetic DBs and mock model responses."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import capstone_compare as b
import experiments as e


class ReviewPathTests(unittest.TestCase):
    def pipeline(self):
        p=e.Pipeline.__new__(e.Pipeline)
        p.chunks=[dict(chunk_id=str(i),title='가상 문서 '+str(i),text='첫 문단 '+str(i)+'\n\n  둘째 문단  \n\n') for i in range(2)]
        p.vectors=np.array([[1.,0.],[0.,1.]],dtype='float32')
        p.query_vector=lambda q:np.array([1.,0.],dtype='float32')
        return p

    def response(self,grades):
        return SimpleNamespace(output_parsed=SimpleNamespace(scores=[e.RankItem(candidate_id=i,relevance=v) for i,v in grades]),usage=None)

    def test_rerank_executes_and_sends_candidate_paragraphs(self):
        api=Mock();api.responses.parse.return_value=self.response([(0,1),(1,4)])
        with patch.object(b,'client',return_value=api):hits,trace,usage=self.pipeline().retrieve('질문','rerank')
        self.assertEqual([h['chunk_id'] for h in hits],['1','0'])
        sent=json.loads(api.responses.parse.call_args.kwargs['input'][1]['content'])
        self.assertEqual(sent['required_candidate_ids'],[0,1])
        self.assertEqual(sent['candidates'][0]['paragraphs'],[{'paragraph_id':0,'text':'첫 문단 0'},{'paragraph_id':1,'text':'둘째 문단'}])
        self.assertEqual(trace['validation_attempts'],1)
        self.assertIsNone(usage)

    def test_rerank_retries_invalid_ids_and_rejects_persistent_duplicates(self):
        api=Mock();api.responses.parse.side_effect=[self.response([(0,4),(0,3)]),self.response([(0,1),(1,4)])]
        with patch.object(b,'client',return_value=api):hits,trace,_=self.pipeline().retrieve('질문','rerank')
        self.assertEqual(trace['validation_attempts'],2)
        api=Mock();api.responses.parse.return_value=self.response([(0,4),(0,3)])
        with patch.object(b,'client',return_value=api),self.assertRaisesRegex(ValueError,'후보 ID'):
            self.pipeline().retrieve('질문','rerank')
        self.assertEqual(api.responses.parse.call_count,2)

    def make_db(self,path):
        # Fabricated nutrient/limit values only, not dietary recommendations.
        foods=[dict(food_code=code,food_name=name,origin='synthetic',basis={'amount':100,'unit':'g'},
                    nutrients={'AD':value},provenance={'source':'synthetic'})
               for code,name,value in [('A','가상음식_A',10),('B','가상음식_B',30)]]
        with sqlite3.connect(path/'foods.sqlite') as db:
            db.executescript('CREATE TABLE foods(food_code TEXT PRIMARY KEY,record_json TEXT); CREATE TABLE aliases(normalized_alias TEXT,food_code TEXT);')
            for food in foods:
                db.execute('INSERT INTO foods VALUES(?,?)',(food['food_code'],json.dumps(food)))
                db.execute('INSERT INTO aliases VALUES(?,?)',(b.food_tools.normalize_name(food['food_name']),food['food_code']))
            db.execute('INSERT INTO aliases VALUES(?,?)',('별칭음식','A'))
        (path/'food_nutrient_definitions.json').write_text(json.dumps([dict(nutrient_id='AD',name='가상성분',unit='mg')]))
        (path/'nutrient_reference_definitions.json').write_text(json.dumps([dict(nutrient_id='synthetic',name='가상성분',unit='mg',food_columns=['AD'],food_factors=[1])]))
        rule=dict(nutrient_id='synthetic',reference_id='fake',reference_type='UL',status='numeric',value=100,min_value=None,max_value=None,unit='mg',intake_scope='total_intake',auto_food_comparison=True,comparator='lte',value_mode='direct',source={'source_id':'SYNTHETIC'},demographic=dict(life_stage='general',sex='both',age_min_months=None,age_max_months_exclusive=None,trimester=None))
        with sqlite3.connect(path/'nutrient_references.sqlite') as db:
            db.execute('CREATE TABLE reference_intakes(record_json TEXT)');db.execute('INSERT INTO reference_intakes VALUES(?)',(json.dumps(rule),))

    def request(self,name='가상음식_A',code='A',daily=False,amount=200):
        return b.Request(question='synthetic',profile=b.Profile(age_years=30,sex='male',life_stage='general'),daily_complete=daily,items=[b.Intake(kind='food',name=name,food_code=code,amount=amount,unit='g')])

    def test_food_name_code_mismatch_blocks_before_arithmetic(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.make_db(path)
            with patch.object(b,'DATA',path),patch.object(b.food_tools,'scale_food') as scale:
                for name,code in [('가상음식_A','B'),('가상음식_B','A'),('가상음식','A'),('별칭음식','B')]:
                    result=b.calculate(self.request(name,code))
                    self.assertEqual(result['status'],'needs_clarification')
                    self.assertEqual(result['items'],[])
                    self.assertIn('음식명과 식품코드',result['clarifications'][0])
                scale.assert_not_called()

    def test_food_canonical_normalization_alias_and_missing_code(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.make_db(path)
            with patch.object(b,'DATA',path),patch.object(b.ref_tools,'OUT',path):
                for name in ['가상음식_A','가상 음식 a','별칭음식']:
                    result=b.calculate(self.request(name))
                    self.assertEqual(result['items'][0]['food']['food_code'],'A')
                    self.assertEqual(b.Decimal(result['items'][0]['nutrients']['가상성분']['amount']),b.Decimal('20'))
                request=self.request();request.items[0].unit='ml'
                unit_mismatch=b.calculate(request)
                self.assertIn('밀도',unit_mismatch['clarifications'][0])
                self.assertEqual(unit_mismatch['items'],[])
                result=b.calculate(self.request(code='MISSING'))
                self.assertEqual(result['status'],'needs_clarification')
                self.assertFalse(any('nutrients' in row for row in result['items']))

    def test_food_mismatch_blocks_natural_extraction_calculate_path(self):
        q='식품코드 B 가상음식_A 200g 먹었어.'
        raw=b.ExtractedRequest(items=[b.ExtractedIntake(kind='food',name='가상음식_A',food_code='B',amount=200,unit='g',evidence=q,intent='reported')])
        api=Mock();api.responses.parse.return_value=SimpleNamespace(output_parsed=raw)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.make_db(path)
            with patch.object(b,'DATA',path),patch.object(b,'client',return_value=api):result=b.calculate(b.parse_question(q))
        self.assertEqual(result['items'],[])
        self.assertIn('음식명과 식품코드',result['clarifications'][0])

    def test_daily_complete_food_status_and_answer_agree(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);self.make_db(path)
            with patch.object(b,'DATA',path),patch.object(b.ref_tools,'OUT',path):
                for daily,status in [(False,'not_above_reference_for_this_food_daily_total_unknown'),(True,'within_reference_for_reported_intake')]:
                    result=b.calculate(self.request(daily=daily))
                    self.assertEqual(result['items'][0]['comparisons'][0]['status'],status)
                    answer=e.guarded_answer(result)
                    self.assertEqual('보고한 하루 총량은 기준을 넘지 않습니다' in answer,daily)
                    self.assertEqual('하루 다른 급원의 섭취는 확인하지 않았습니다' in answer,not daily)
                above=b.calculate(self.request(daily=True,amount=1100))
                self.assertEqual(above['items'][0]['comparisons'][0]['status'],'above_UL_for_reported_intake')
                self.assertIn('기준을 초과합니다',e.guarded_answer(above))

    def test_baseline_t1_clarification_and_empty_evidence(self):
        api=Mock();api.responses.create.return_value=SimpleNamespace(output_text='확인해주세요. [T1] [T99]',usage=None)
        for issues,unknown in [(['섭취량 확인'],['T99']),([],['T1','T99'])]:
            request=b.Request(question='질문',input_issues=issues)
            with patch.object(b,'client',return_value=api),patch.object(b,'retrieve',return_value=[]):result=b.answer(request)
            self.assertEqual(result['citation_check']['unknown_ids'],unknown)
            self.assertEqual(result['citation_check']['unknown_ids'],e.citation_audit(result['answer'],[],result['calculation'])['unknown_ids'])

    def test_t1_evidence_predicate_shared_for_all_tool_shapes(self):
        for tools,allowed in [({'items':[{}]},True),({'clarifications':['확인']},True),({'concept_calculation':{'rows':[1]}},True),({'items':[],'clarifications':[]},False)]:
            self.assertEqual(b.has_tool_evidence(tools),allowed)
            self.assertEqual(e.citation_audit('[T1]',[],tools)['unknown_ids'],[] if allowed else ['T1'])

if __name__=='__main__':unittest.main()
