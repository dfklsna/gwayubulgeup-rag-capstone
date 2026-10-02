"""Embed first-party runtime helpers in the exact required submission entry point."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BEGIN='# BEGIN GENERATED STANDALONE SUPPORT\n'
END='# END GENERATED STANDALONE SUPPORT\n'
FILES=('src/experiments.py','src/input_grounding.py','src/knowledge_rules.py','src/knowledge_sources.json',
       'scripts/query_food.py','scripts/query_reference_intakes.py','requirements.txt',
       'examples/selected_strategy.json','examples/evaluation_questions.jsonl')


def generated():
    data={name:{'sha256':hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),'text':(ROOT/name).read_text()} for name in FILES}
    return BEGIN+'_EMBEDDED_SUPPORT = '+repr(data)+'\n\n'+(ROOT/'scripts/standalone_bootstrap.py').read_text()+END


def build(check=False):
    path=ROOT/'src/capstone_compare.py';text=path.read_text()
    start=text.index(BEGIN);end=text.index(END,start)+len(END)
    output=text[:start]+generated()+text[end:]
    if check:
        if output!=text:raise SystemExit('Embedded support is stale: run python scripts/build_standalone.py')
    else:path.write_text(output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    build(parser.parse_args().check)
