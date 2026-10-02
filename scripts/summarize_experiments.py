"""Publish aggregate evidence without third-party full texts, credentials or intake logs."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import experiments as e
import capstone_compare as b

PATHS={
    'baseline':'results/runs/baseline_01',
    **{v:f'results/comparisons/ablation_01/{v}' for v in e.VARIANTS},
    'rerank':'results/comparisons/rerank_validated_01/rerank',
    'guard':'results/comparisons/final_validation_01/guard',
    'combined':'results/comparisons/final_01',
}

OBSERVATIONS={
'baseline':'카페인 2문항 검색 누락. 음식 안전·부족 단정과 잔당 함량 추정.',
'hybrid':'성인 카페인 회복. 디카페인 근거 누락으로 회귀. 복합 문항은 출처 ID만 찾고 필요한 수치가 없는 청크를 선택.',
'mmr':'검색 6/8 유지. 음식 판정과 커피 잔당 함량 추정 오류 지속.',
'rerank':'후보 전체 형식 검증 보완 후 12문항 재실행. 검색 6/8 유지. 450mg을 400mg보다 112.5% 초과라고 표현하는 등 생성 오류 지속.',
'topic_filter':'8/8 출처 및 필요한 카페인 문맥 회복. 단독 적용에서는 계산 해석·잔당 함량 추정 오류 지속.',
'compression':'생성 입력 감소. 카페인 400mg/300mg 문맥 삭제 회귀. 출처 ID 지표만으로 손실을 발견할 수 없음.',
'guard':'명시적 섭취 항목 5개를 코드 렌더링으로 처리. 일반 질문은 원래 답변 재사용. UL, CDRR, 권고 미만 조건을 구분.',
'citations':'잘못 연결한 근거 ID 제거. 원래 사실 내용을 바꾸지 않으므로 판단 오류는 남음.',
'combined':'주제 필터+계산/확인 강화+인용 검증. 출처 8/8, 섭취 질문 5개 결정적 답변. 일반 비타민 A 설명의 UL 해석 오류는 남음.'}


def collect():
    reports={}
    for variant,relative in PATHS.items():
        folder=ROOT/relative
        rows=[]
        for path in sorted(folder.glob('*.json')):
            row=json.loads(path.read_text())
            if not isinstance(row,dict) or 'case_id' not in row:continue
            row['citation_check']=e.citation_audit(row['answer'],row['retrieved'],row['calculation'])
            row.setdefault('generation_method','llm')
            row.setdefault('context_characters',len(json.dumps({'T1':row['calculation'],'documents':row['retrieved']},ensure_ascii=False)))
            rows.append(row)
        if len(rows)!=12:raise ValueError(f'{variant}: completed 12 cases required, got {len(rows)}')
        summary=e.summarize(rows)
        summary.update(artifact=relative,observation=OBSERVATIONS[variant],reviewer='assistant',human_reviewed=False,
            per_case=[{'case_id':r['case_id'],'source_recall_at_k':r['source_recall_at_k'],
                       'retrieved_source_ids':[h['source_id'] for h in r['retrieved']],
                       'unsupported_citation_ids':r['citation_check']['unknown_ids'],
                       'generation_method':r['generation_method']} for r in rows])
        reports[variant]=summary
    output={'schema_version':1,'date':'2026-10-02','question_count':12,'retrieval_scored_cases':8,
            'metric':'source ID Recall@5, not answer accuracy or passage recall',
            'citation_metric':'same current ID parser applied to every saved answer; not entailment verification',
            'limitations':['개발 질문으로 설정 선택; 독립 검증 아님','LLM 생성 1회 실행, 신뢰구간 없음','재사용 답변의 신규 API 토큰0은 서비스 원가0을 의미하지 않음','성공한 생성/재순위화 호출의 기록만 집계. 입력 추출·임베딩·중단 시도 비용은 포함하지 않음'],
            'variants':reports}
    b.write_json(ROOT/'results/comparison_summary.json',output)
    return output


if __name__=='__main__':
    for name,r in collect()['variants'].items():
        print(name,r['source_recall_at_k'],r['unsupported_citation_cases'],r['generation_input_tokens'])
