#!/usr/bin/env python3
"""rebuild_judged_union.py - rebuild judged.csv after a partial re-judge.

The --only-exp7 re-judge overwrites judged.csv with only its rows. This
merges the pre-re-judge full file (kept at judged_full_backup.csv) with the
new file: non-EXP-7 rows from the backup, EXP-7 rows from the new file.
Run AFTER the re-judge completes, then re-run merge_judged.py.
"""
import csv, sys
from pathlib import Path
csv.field_size_limit(2**31-1)
OUT_DIR = Path(__file__).resolve().parent.parent / "output"
BACKUP = OUT_DIR / "judged_full_backup.csv"
CURRENT = OUT_DIR / "judged.csv"
FIELDS = ["session_id","turn","cell","model","protocol","case","t1_adoption","t2_severity","justification","context_mode","judged_at"]

rows = {}
for f, tag in [(CURRENT, "new"), (BACKUP, "backup")]:
    if not f.exists(): 
        print(f"missing {f}"); sys.exit(1)
    with open(f, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (r["session_id"], int(r["turn"]))
            # new (re-judged) rows win; keep backup rows for everything else
            if key not in rows or tag == "new":
                rows[key] = r

tmp = CURRENT.with_suffix(".csv.tmp")
with open(tmp, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    w.writeheader()
    for r in rows.values():
        w.writerow({k: r.get(k, "") for k in FIELDS})
tmp.replace(CURRENT)
print(f"judged.csv rebuilt: {len(rows)} rows (union of backup + re-judged)")
