import hashlib
import json
from pathlib import Path
import sys
import unittest
from decimal import Decimal
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import knowledge_rules as k
import experiments as e
import capstone_compare as b


class KnowledgeRulesTests(unittest.TestCase):
    def fixture(self,concept):
        text='직접 작성한 합성 근거. 실제 건강 기준이 아님.'
        chunk={'chunk_id':'synthetic','source_id':'S','text':text,'title':'합성 근거'}
        spec={'sources':[{'chunk_id':'synthetic','text_sha256':hashlib.sha256(text.encode()).hexdigest()}]}
        if concept=='salt_equivalent':spec['salt_per_sodium']='2.5'
        if concept=='reference_types':spec['sources']*=2
        return [chunk],{'concepts':{concept:spec}}

    def test_salt_both_directions_and_units(self):
        self.assertEqual(Decimal(k.salt_equivalent('1200','mg','sodium','2.5')['output_amount_mg']),3000)
        self.assertEqual(Decimal(k.salt_equivalent('6','g','salt','2.5')['output_amount_mg']),2400)
        for v in ['0','-1','NaN','Infinity']:
            with self.assertRaises(ValueError):k.salt_equivalent(v,'mg','sodium','2.5')

    def test_quantities_bound_to_named_substance_not_user_age(self):
        chunks,catalog=self.fixture('salt_equivalent')
        result=k.render_concept('30세야. 소금 6g과 나트륨 1200mg은 얼마나 달라?',chunks,catalog)
        rows=result['calculation']['rows']
        self.assertEqual([(r['kind'],r['output_amount_mg']) for r in rows],[('salt','2.40E+3'),('sodium','3000.0')])
        self.assertIn('근사',result['answer'])
        self.assertIn('측정한 값은 아닙니다',result['answer'])

    def test_missing_or_changed_evidence_abstains_without_calculation(self):
        chunks,catalog=self.fixture('salt_equivalent')
        for data in [[],[{**chunks[0],'text':'변경된 원문'}]]:
            result=k.render_concept('나트륨 1000mg은 소금 몇 g?',data,catalog)
            self.assertEqual(result['status'],'source_unavailable')
            self.assertIsNone(result['calculation'])
            self.assertNotIn('2500',result['answer'])

    def test_definition_cannot_expand_into_legal_obligation(self):
        chunks,catalog=self.fixture('sugars')
        result=k.render_concept('첨가당을 반드시 표기해야 하는 법적 의무야?',chunks,catalog)
        self.assertIn('답변을 보류',result['answer'])
        self.assertNotIn('표기해야 합니다',result['answer'])

    def test_reference_purpose_not_nutrient_specific_ul_reason(self):
        chunks,catalog=self.fixture('reference_types')
        result=k.render_concept('칼슘 권장량 넘으면 UL 초과야?',chunks,catalog)
        self.assertIn('판단하지 않습니다',result['answer'])
        self.assertNotIn('칼륨',result['answer'])
        self.assertIsNone(k.concept_for('감자 200g의 열량 계산'))

    def test_salt_calculation_citation_is_valid(self):
        self.assertEqual(e.citation_audit('[T1][D1]',[{'citation':'D1'}],{'concept_calculation':{'rows':[{}]}})['unknown_ids'],[])

    def test_routing_stops_generation_when_source_is_missing(self):
        pipeline=Mock();pipeline.chunks=[];pipeline.retrieve.return_value=([],{},None)
        with patch.object(b,'client') as client:
            result=e.answer_variant(b.Request(question='나트륨 100mg은 소금 얼마?'),'combined',pipeline,e.Strategy(guard=True,bounded_concepts=True,citations=True))
        client.assert_not_called()
        self.assertEqual(result['generation_method'],'bounded_concept_renderer')
        self.assertIn('보류',result['answer'])


@unittest.skipUnless((ROOT/'data/index/chunks.jsonl').exists(),'Full third-party index not present')
class LocalKnowledgeSourceTests(unittest.TestCase):
    def test_all_anchors_present_and_relevant(self):
        chunks=[json.loads(l) for l in (ROOT/'data/index/chunks.jsonl').read_text().splitlines()]
        catalog=json.loads(k.CATALOG.read_text())
        markers={'salt_equivalent':['2,000','소금','5 g'], 'reference_types':['상한섭취량','충분섭취량'], 'sugars':['총당류','첨가당'], 'caffeine_sources':['consider all sources']}
        for concept in catalog['concepts']:
            hits,_=k.bind_sources(concept,chunks)
            self.assertTrue(hits,concept)
            text=' '.join(h['text'] for h in hits)
            for marker in markers[concept]:self.assertIn(marker,text)


if __name__=='__main__':unittest.main()
