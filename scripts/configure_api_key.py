"""Save an OpenAI key locally using a masked native macOS dialog or terminal input."""
import getpass
import os
from pathlib import Path
import subprocess
import sys

from dotenv import set_key

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform == 'darwin':
        script = '''set reply to display dialog "OpenAI API 키를 붙여넣고 저장을 누르세요. 키는 이 프로젝트의 .env에만 저장됩니다." with title "과유불급 · API 키 설정" default answer "" with hidden answer buttons {"취소", "저장"} default button "저장" cancel button "취소"
return text returned of reply'''
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
        if result.returncode:
            print('입력을 취소했거나 입력 창을 열지 못했습니다. 키를 변경하지 않았습니다.')
            return 1
        key = result.stdout.strip()
    else:
        key = getpass.getpass('OpenAI API key (hidden): ').strip()
    if not key.startswith('sk-') or any(c.isspace() for c in key):
        print('키 형식을 확인해주세요. 키를 변경하지 않았습니다.')
        return 1
    path = ROOT / '.env'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write((ROOT / '.env.example').read_text())
    os.chmod(path, 0o600)
    set_key(str(path), 'OPENAI_API_KEY', key)
    os.chmod(path, 0o600)
    print('API 키를 로컬 .env에 저장했습니다. 키 값은 출력하지 않습니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
