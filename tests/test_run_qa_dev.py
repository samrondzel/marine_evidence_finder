from scripts.run_qa_dev import load_dev_questions
from pathlib import Path
import json

def test_dev_only(tmp_path: Path):
    p = tmp_path / "bench.jsonl"
    p.write_text('\n'.join(json.dumps({"id": i, "split": split}) for i,split in [('a','dev'),('b','test')]), encoding='utf8')
    assert [x['id'] for x in load_dev_questions(p)] == ['a']
