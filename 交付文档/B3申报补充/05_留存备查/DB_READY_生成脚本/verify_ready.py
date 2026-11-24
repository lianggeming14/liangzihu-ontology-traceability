"""Validate the actual delivered CSV files and already-loaded SQLite database."""
import argparse,json,sqlite3,hashlib
from pathlib import Path
from database_io import load_csv_directory
from build_ready import validate,dump

def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,default=Path(__file__).resolve().parents[1]);a=p.parse_args();out=a.directory.resolve()
    schema=json.loads((out/'schema/schema.json').read_text('utf-8'))
    t=load_csv_directory(out,schema)
    checks,issues=validate(t,schema,out)
    con=sqlite3.connect('file:'+str(out/'database/wuchang_2025.sqlite').replace('\\','/')+'?mode=ro',uri=True)
    fk=con.execute('PRAGMA foreign_key_check').fetchall();integrity=con.execute('PRAGMA integrity_check').fetchall()
    counts={name:con.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0] for name in t}
    con.close();mismatch={name:[len(rows),counts[name]] for name,rows in t.items() if len(rows)!=counts[name]}
    bad=[c for c in checks if not c['passed']]
    report={'passed':not(bad or issues or fk or mismatch) and integrity==[('ok',)],'tables':len(t),'rows':sum(map(len,t.values())),'csv_business_checks':len(checks),'failed_business_checks':bad,'remaining_issues':issues,'sqlite_foreign_key_errors':fk,'sqlite_integrity':integrity,'csv_sqlite_count_mismatch':mismatch,'csv_hashes':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((out/'csv').glob('*.csv'))}}
    dump(out/'reports/independent_verification.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='csv_hashes'},ensure_ascii=False))
    if not report['passed']:raise SystemExit(1)
if __name__=='__main__':main()
