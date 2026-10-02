# Template embedded in src/capstone_compare.py by build_standalone.py.
_USER_ROOT = Path(__file__).resolve().parent
if _USER_ROOT.name == 'src':
    _USER_ROOT = _USER_ROOT.parent
_BUNDLE_TEMP = None


def _support_root():
    global _BUNDLE_TEMP
    required = ('scripts/query_food.py', 'scripts/query_reference_intakes.py',
                'src/experiments.py', 'src/input_grounding.py', 'src/knowledge_rules.py',
                'src/knowledge_sources.json', 'examples/selected_strategy.json')
    if all((_USER_ROOT / name).is_file() for name in required):
        return _USER_ROOT
    import tempfile
    _BUNDLE_TEMP = tempfile.TemporaryDirectory(prefix='rag-capstone-')
    target = Path(_BUNDLE_TEMP.name)
    for name, entry in _EMBEDDED_SUPPORT.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid bundled path')
        raw = entry['text'].encode('utf-8')
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Bundled support integrity check failed')
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return target


if __name__ == '__main__' and sys.argv[1:] in (['--help'], ['-h'], []):
    print('''과유불급 RAG capstone (Python 3.12)
Usage: python capstone_compare.py COMMAND [OPTIONS]

Standalone, standard-library commands:
  --help          Show this help without installing packages or data
  --demo          Run a synthetic food calculation offline
  --requirements  Print required packages for full RAG execution

Full commands (external packages required):
  prepare | build | foods NAME
  calculate --request FILE
  ask (--question TEXT | --request FILE) [--variant combined|baseline]
  evaluate --questions FILE --output DIR
  compare --output DIR [--variants ...]

Local helper modules and selected configuration are embedded in this file.
Full RAG additionally needs packages, OPENAI_API_KEY, and corpus/index data.
Set RAG_DATA_DIR and RAG_CACHE_DIR to their paths. No secrets or real DBs are embedded.
''')
    raise SystemExit(0)

if __name__ == '__main__' and sys.argv[1:] == ['--requirements']:
    print(_EMBEDDED_SUPPORT['requirements.txt']['text'], end='')
    raise SystemExit(0)

ROOT = _support_root()
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
if __name__ == '__main__':
    sys.modules.setdefault('capstone_compare', sys.modules[__name__])

if __name__ == '__main__' and sys.argv[1:] == ['--demo']:
    from query_food import scale_food
    record = {'food_code':'DEMO-001','food_name':'가상음식','origin':'synthetic',
              'basis':{'amount':100,'unit':'g'},'provenance':{'source':'synthetic'},
              'nutrients':{'energy_kcal':80,'sodium_mg':30,'unknown':None}}
    result = scale_food(record, Decimal('200'), 'g')
    print(json.dumps({'mode':'offline_synthetic_not_health_assessment','result':result},ensure_ascii=False,indent=2))
    raise SystemExit(0)
