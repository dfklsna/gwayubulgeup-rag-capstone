import json,hashlib,sqlite3,sys
from pathlib import Path
from collections import Counter
from decimal import Decimal
from datetime import datetime,timezone
sys.path.insert(0,'scripts')
from prepare_food_db import read_workbook
P=Path('data/prepared');ROOT=Path('..');C=ROOT/'collection_runs/20261002'
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks={};counts={}
docs=rows(P/'documents.jsonl');old=rows(P/'legacy_documents.jsonl');all_docs=rows(P/'all_documents.jsonl');entities=rows(P/'entities.jsonl')
checks['document_counts']=len(docs)==136 and len(old)==63 and len(all_docs)==199
checks['unique_document_ids']=len({d['document_id'] for d in all_docs})==199
checks['all_document_text_hashes']=all(hashlib.sha256(d['text'].encode()).hexdigest()==d['text_sha256'] for d in all_docs)
checks['current_and_legacy_integration']= {d['document_id']:d['text_sha256'] for d in docs+old}=={d['document_id']:d['text_sha256'] for d in all_docs}
checks['retrieval_candidate_separation']=sum(d['preferred_for_baseline'] for d in all_docs)==136 and all(not d['preferred_for_baseline'] for d in all_docs if d['document_id'] in {x['document_id'] for x in old})
checks['legacy_inputs_unchanged']=all(sha(ROOT/name)==h for name,h in json.loads((P/'legacy_input_hashes.json').read_text()).items())
checks['legacy_stored_copies']=all(sha(P/r['stored_original'])==r['sha256'] for r in rows(P/'legacy_file_manifest.jsonl') if 'stored_original' in r)
checks['legacy_text_exports']=all((P/'legacy_texts'/f"{d['document_id']}.txt").read_text()==d['text']+'\n' for d in old)
checks['health_topics']=len(entities)==108 and sum(e['domain']=='easter_egg' for e in entities)==2
checks['exact_duplicate_content_within_current_source']=len({(d['source_id'],d['text_sha256']) for d in docs})==len(docs)
checks['catalog_document_counts']=json.loads((P/'data_catalog.json').read_text())['documents']['records']==len(all_docs)
summary=json.loads((P/'food_preprocessing_summary.json').read_text());copy=P/'food_originals'/Path(summary['source_workbook']).name
checks['food_workbook_hash']=sha(copy)==summary['source_sha256']
defs=json.loads((P/'food_nutrient_definitions.json').read_text());columns=[d['nutrient_id'] for d in defs]
source=iter(read_workbook(copy));_,_,_,headers=next(source)
checks['food_column_definitions']=len(defs)==134 and all(headers[d['nutrient_id']]==d['source_header'] for d in defs)
food_counts=Counter();coverage=Counter();food_codes=set();bad=[];nutrient_cells=0;zeros=0;missing=0
with (P/'food_records.jsonl').open() as f, sqlite3.connect(f'file:{P/"foods.sqlite"}?mode=ro',uri=True) as db:
 checks['food_sqlite_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 for (_,_,row,raw),line in zip(source,f,strict=True):
  r=json.loads(line);code=r['food_code'];food_codes.add(code);food_counts[r['basis']['raw']]+=1
  if raw['A']!=code or raw['B']!=r['food_name'] or r['provenance']['row']!=row:bad.append([row,'identity'])
  if db.execute('select record_json from foods where food_code=?',(code,)).fetchone()[0]!=line.rstrip('\n'):bad.append([row,'sqlite_mismatch'])
  for key in columns:
   v=raw.get(key,'');actual=r['nutrients'][key];nutrient_cells+=1
   if v=='':
    missing+=1
    if actual is not None:bad.append([row,key,'missing_as_value'])
   else:
    coverage[key]+=1;zeros+=Decimal(v)==0
    if actual is None or Decimal(str(actual))!=Decimal(v):bad.append([row,key,'value_mismatch'])
 checks['food_row_count']=len(food_codes)==19617==db.execute('select count(*) from foods').fetchone()[0]
 checks['all_food_alias_foreign_keys']=db.execute('SELECT count(*) FROM aliases a LEFT JOIN foods f USING(food_code) WHERE f.food_code IS NULL').fetchone()[0]==0
 checks['jellyfish_alias_four_candidates']=db.execute('SELECT count(*) FROM aliases WHERE normalized_alias=?',('해파리냉채',)).fetchone()[0]==4
checks['all_2628678_food_cells_match_workbook']=not bad and nutrient_cells==2628678
checks['food_basis_counts']=dict(food_counts)=={'100g':13877,'100ml':5740}
checks['food_missing_and_zero_preserved']=missing==2306959 and zeros==46572
refs=rows(P/'nutrient_reference_intakes.jsonl');cell_ids={c['cell_id'] for c in rows(P/'kdri_reference_cells.jsonl')}
with sqlite3.connect(f'file:{P/"nutrient_references.sqlite"}?mode=ro',uri=True) as db:
 checks['reference_sqlite_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 stored={r[0]:json.loads(r[1]) for r in db.execute('SELECT reference_id,record_json FROM reference_intakes')}
 checks['reference_jsonl_sqlite_agree']=stored=={r['reference_id']:r for r in refs}
checks['reference_cell_provenance']=all(r['source']['cell_id'] in cell_ids for r in refs if r['source']['cell_id'])
checks['reference_food_column_mapping']=all(c in columns for d in json.loads((P/'nutrient_reference_definitions.json').read_text()) for c in d['food_columns'])
checks['reference_hash_current']=json.loads((P/'nutrient_reference_validation.json').read_text())['reference_sha256']==sha(P/'nutrient_reference_intakes.jsonl')
status=rows(C/'source_status.jsonl');legacy_manifest=rows(P/'legacy_file_manifest.jsonl')
limitations={
 'current_ocr_pending':[r['source_id'] for r in status if r['ocr_pending_paths']],
 'legacy_ocr_pending':[{'path':r['input_path'],'record':r} for r in legacy_manifest if r['disposition']=='needs_ocr'],
 'missing_attachments':Counter(r['source_id'] for r in rows(C/'collection_failures.jsonl')),
 'documents_with_non_ocr_images':sum(bool(d['preprocessing'].get('images')) for d in docs),
 'merged_html_tables':sum(any(c['rowspan']!='1' or c['colspan']!='1' for row in t['rows'] for c in row) for d in docs for t in d['tables']),
 'pdf_documents_with_table_review_caveat':sum(d['raw_kind']=='pdf' for d in docs),
 'food_basis_counts':dict(food_counts),
 'food_nutrient_coverage':{d['source_header']:coverage[d['nutrient_id']] for d in defs if d['nutrient_id'] in ['R','T','U','W','X','Y','AD','AE','AL','AZ']},
 'food_coverage_examples':'non-null values include explicit zero; absence was not filled',
 'reference_non_automatic_nutrients':sorted({r['nutrient_name'] for r in refs if r['status']=='numeric' and not r['auto_food_comparison']})}
report={'reviewed_at':datetime.now(timezone.utc).isoformat(),'integrity_passed':all(checks.values()),'checks':checks,'errors':bad[:20],
 'counts':{'documents':len(all_docs),'current_documents':len(docs),'legacy_documents':len(old),'foods':len(food_codes),'references':len(refs),'food_cells_checked':nutrient_cells},
 'limitations':limitations,'conclusion':'Prepared subset is usable for scoped baseline experiments; entire collected corpus is not exhaustively OCRed or semantically reviewed.'}
(P/'data_preparation_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':report['integrity_passed'],'checks':len(checks),'failed':[k for k,v in checks.items() if not v],'limitations':{k:v for k,v in limitations.items() if k!='legacy_ocr_pending'},'legacy_ocr_pending':limitations['legacy_ocr_pending']},ensure_ascii=False,indent=2))
