"""Store replies explicitly supplied by the user as future training data."""

import json
from pathlib import Path
from threading import Lock


class StyleSampleStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = Lock()

    def _read(self):
        if not self.path.exists():
            return []
        records = []
        for number, line in enumerate(self.path.read_text(encoding='utf-8').splitlines(), 1):
            if line.strip():
                try:
                    record = json.loads(line)
                    messages = record['messages']
                    if (len(messages) != 2 or messages[0]['role'] != 'user'
                            or messages[1]['role'] != 'assistant'
                            or any(not isinstance(m['content'], str) or not m['content'].strip() for m in messages)):
                        raise ValueError('Expected a user/assistant text pair')
                    records.append(record)
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(f'训练样本第 {number} 行格式有误') from error
        return records

    def count(self):
        with self.lock:
            return len(self._read())

    def add(self, incoming, own_reply):
        incoming, own_reply = incoming.strip(), own_reply.strip()
        if not incoming or not own_reply:
            raise ValueError('请填写对方的消息和你自己的回复')
        record = {'messages': [
            {'role': 'user', 'content': incoming},
            {'role': 'assistant', 'content': own_reply},
        ]}
        with self.lock:
            records = self._read()
            if record in records:
                return False, len(records)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            return True, len(records) + 1
