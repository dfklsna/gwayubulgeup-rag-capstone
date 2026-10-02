"""Build an allowlisted source-only folder and ZIP, excluding credentials and corpora."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TREES=('src','scripts','tests','examples','docs','.github')
FILES=('README.md','requirements.txt','requirements-preprocessing.txt','.env.example','.gitignore',
       'data/README.md','data/source_manifest.json','data/demo/.gitkeep',
       'results/design.md','results/evaluation.md','results/comparison_summary.json',
       'results/holdout_summary.json','results/revision_summary.json','results/release_summary.json','results/submission_review_summary.json','results/grounding_v2_summary.json','results/coverage_summary.json','results/context_grounding_summary.json')
SUFFIXES={'.py','.json','.jsonl','.md','.yml','.yaml'}
SECRET=re.compile(r'(?:sk-proj-|gh[pousr]_)[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')


def public_files():
    paths={ROOT/f for f in FILES if (ROOT/f).is_file()}
    for folder in TREES:
        paths.update(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in SUFFIXES and '__pycache__' not in p.parts)
    for path in sorted(paths):
        if path.is_symlink():raise ValueError('공개 묶음에 심볼릭 링크를 포함하지 않습니다.')
        yield path


def build(output):
    output=Path(output).resolve()
    archive=output.with_suffix('.zip')
    if output.exists() or archive.exists():raise ValueError('기존 출력 폴더/ZIP을 덮어쓰지 않습니다.')
    files=list(public_files())
    # Validate every input before writing a partial release.
    for path in files:
        text=path.read_text(encoding='utf-8')
        if SECRET.search(text):raise ValueError('공개 후보에 키 형식 문자열이 있습니다: '+str(path.relative_to(ROOT)))
        if re.search('/'+'Users'+r'/[^/\s]+/',text):raise ValueError('공개 후보에 개인 로컬 경로가 있습니다: '+str(path.relative_to(ROOT)))
    output.mkdir(parents=True)
    manifest=[]
    for path in files:
        relative=path.relative_to(ROOT);target=output/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        manifest.append({'path':relative.as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    (output/'PUBLIC_MANIFEST.json').write_text(json.dumps({'kind':'source_only_no_credentials_or_third_party_corpus','files':manifest},ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(output.rglob('*')):
            if path.is_file():z.write(path,Path(output.name)/path.relative_to(output))
    return {'files':len(manifest),'folder':str(output),'zip':str(archive)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.output),ensure_ascii=False,indent=2))
