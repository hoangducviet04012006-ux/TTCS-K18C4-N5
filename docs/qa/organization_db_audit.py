"""Read-only verification against the pre-organization snapshot; no app imports."""
from pathlib import Path
import hashlib
import json
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'docs/qa'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    result = {}
    for path in sorted(ROOT.rglob('*.db')):
        if '.venv' in path.parts or '.git' in path.parts:
            continue
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
            tables = {}
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
                rows = db.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid').fetchall()
                tables[name] = {'count': len(rows), 'sha256': hashlib.sha256(repr(rows).encode()).hexdigest()}
            result[str(path.relative_to(ROOT))] = {
                'file_sha256': digest(path),
                'schema_sha256': hashlib.sha256(repr(schema).encode()).hexdigest(),
                'tables': tables,
                'integrity': db.execute('PRAGMA integrity_check').fetchall(),
            }
    return result


if __name__ == '__main__':
    current = json.loads(json.dumps(snapshot()))
    (QA / 'organization_after.json').write_text(json.dumps(current, indent=2), encoding='utf8')
    before = json.loads((QA / 'organization_before.json').read_text(encoding='utf8'))
    assert current == before, 'Database content or file changed; inspect snapshots.'
    recall = json.loads((QA / 'organization_recall_before.json').read_text(encoding='utf8'))
    assert all(digest(ROOT / name) == value for name, value in recall.items()), 'Recall code changed'
    (QA / 'organization_tree_after.txt').write_text('\n'.join(sorted(p.name + ('/' if p.is_dir() else '') for p in ROOT.iterdir())), encoding='utf8')
    launchers = [p.name for p in ROOT.iterdir() if p.suffix.lower() in {'.bat', '.cmd', '.ps1', '.vbs'}]
    assert launchers == ['start_demo.bat'], launchers
    print(f'PASS: all {len(current)} databases identical byte-for-byte, schemas and every table unchanged; Recall code unchanged; one root launcher.')
