"""Check the actual Git export; fail closed and never print secret values."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORBIDDEN = {'.env', 'config_ai.env', 'accounts.json', 'assistant-auth.json', 'deployment.json'}
FORBIDDEN_PARTS = {'datas', 'node_modules', '.venv', 'venv', '__pycache__', 'browser_profiles', 'conversation_memory'}
PATTERNS = {
    'GitHub token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}'),
    'API key': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    'session cookie': re.compile(r'\bsessionid(?:_ss)?=[A-Za-z0-9%._-]{20,}'),
    'private key material': re.compile(r'-----BEGIN (?:EC |RSA |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{40,}'),
    'private Windows profile path': re.compile(r'[A-Z]:\\Users\\[^\\\s"\']+\\'),
}


def scan_file(path, content):
    relative = Path(path)
    findings = []
    if relative.name in FORBIDDEN or FORBIDDEN_PARTS.intersection(relative.parts):
        findings.append('private runtime file')
    if relative.suffix in {'.gguf', '.safetensors', '.log', '.zip', '.pyc'}:
        findings.append('runtime or model artifact')
    text = content.decode('utf-8', errors='replace')
    for label, pattern in PATTERNS.items():
        if pattern.search(text):
            findings.append(label)
    if relative.name.endswith('.env.example') or relative.name == '.env.example':
        for line in text.splitlines():
            if re.match(r'\s*(AI_API_KEY|DY_COOKIES|WEB_PROTECT|KEYS)\s*=', line):
                value = line.split('=', 1)[1].strip().strip('"\'')
                if value:
                    findings.append('example contains credential value')
    return findings


def main():
    mode = '--cached' if '--staged' in sys.argv else 'HEAD'
    try:
        listed = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT)
        files = [name.decode('utf-8') for name in listed.split(b'\0') if name]
        if not files:
            raise RuntimeError('No Git files were selected.')
        failures = []
        for name in files:
            revision = ':' + name if mode == '--cached' else 'HEAD:' + name
            content = subprocess.check_output(['git', 'show', revision], cwd=ROOT, stderr=subprocess.DEVNULL)
            failures.extend((name, reason) for reason in scan_file(name, content))
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print('Scan could not read the selected Git export; refusing publication.')
        return 2
    for name, reason in failures:
        print(f'{name}: {reason}')
    print(f'Checked {len(files)} Git files; {len(failures)} finding(s).')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
