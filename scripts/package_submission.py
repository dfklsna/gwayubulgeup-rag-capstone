"""Package exactly the three required capstone files, without replacing old output."""
import argparse
from pathlib import Path
import shutil
import zipfile

from build_standalone import build as check_bundle

ROOT = Path(__file__).resolve().parents[1]
FILES = ('src/capstone_compare.py', 'results/design.md', 'results/evaluation.md')


def build(output):
    check_bundle(check=True)
    output = Path(output).resolve()
    archive = output.with_suffix('.zip')
    if output.exists() or archive.exists():
        raise ValueError('기존 폴더/ZIP을 덮어쓰지 않습니다.')
    for name in FILES:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(name)
    for name in FILES:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            z.write(output / name, name)
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(build(parser.parse_args().output))
