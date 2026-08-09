"""integritylib.resume - batch checkpoint/resume machinery.

Each runner writes unified-schema batches (output/integrity/{tag}_batch_NNN.csv).
On startup, completed session_ids are scanned from existing batches and
skipped, so an interrupted run resumes without re-running finished sessions.
Batches flush every FLUSH_SESSIONS completed sessions.
"""

import csv
import threading
import time
from typing import Dict, List, Set

from .config import OUTPUT_DIR
from .session import SESSION_SCHEMA

FLUSH_SESSIONS = 25

_csv_lock = threading.Lock()
_progress_lock = threading.Lock()


def scan_completed(tag: str) -> Set[str]:
    """Session ids fully written to batch CSVs.

    Batches are written atomically (temp file + rename), so any session_id
    present in a batch file is a complete session; a crash cannot leave a
    partially written batch behind.
    """
    done: Set[str] = set()
    if not OUTPUT_DIR.exists():
        return done
    for f in sorted(OUTPUT_DIR.glob(f"{tag}_batch_*.csv")):
        try:
            with open(f, newline="", encoding="utf-8", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    sid = row.get("session_id", "")
                    if sid:
                        done.add(sid)
        except Exception as e:
            print(f"  WARN: could not read {f}: {e}")
    return done


def purge_error_sessions(tag: str) -> list:
    """Remove sessions containing API-error rows from the batch files.

    Per pre_registration.md section 4: sessions with an API failure after
    one retry are excluded, logged, and re-run at the end of the batch.
    Removing their rows here means the next invocation of the runner
    re-runs them (resume sees them as not done).
    Returns the list of purged session_ids.
    """
    purged = []
    for f in sorted(OUTPUT_DIR.glob(f"{tag}_batch_*.csv")):
        try:
            with open(f, newline="", encoding="utf-8", errors="replace") as fh:
                rows = [r for r in csv.DictReader(fh)]
        except Exception as e:
            print(f"  WARN: could not read {f}: {e}")
            continue
        if not rows:
            continue
        bad = {r["session_id"] for r in rows if r.get("finishReason") == "error"}
        if not bad:
            continue
        kept = [r for r in rows if r["session_id"] not in bad]
        tmp = f.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=SESSION_SCHEMA)
            writer.writeheader()
            for r in kept:
                writer.writerow({k: r.get(k, "") for k in SESSION_SCHEMA})
        tmp.replace(f)
        purged.extend(sorted(bad))
    if purged:
        print(f"  PURGED {len(purged)} error sessions from {tag} batches "
              f"(will be re-run on next invocation): {purged[:5]}{'...' if len(purged) > 5 else ''}")
    return purged


def run_tasks_per_model(todo: list, worker_fn, workers_per_model: int = 5) -> int:
    """Run tasks with an independent worker pool PER MODEL.

    Each model (gemini/gpt/glm) gets its own ThreadPoolExecutor with
    workers_per_model threads, so e.g. 5 Gemini + 5 GPT + 5 GLM calls can
    run concurrently (up to 15 total). The GLM semaphore still caps GLM at
    GLM_MAX_CONCURRENCY as a safety net.
    Returns the number of failed tasks.
    """
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor, as_completed

    by_model = defaultdict(list)
    for t in todo:
        by_model[t["model"]].append(t)

    executors = {}
    futures = {}
    for model, ts in by_model.items():
        ex = ThreadPoolExecutor(max_workers=workers_per_model)
        executors[model] = ex
        for t in ts:
            futures[ex.submit(worker_fn, t)] = t

    failed = 0
    for fut in as_completed(futures):
        t = futures[fut]
        try:
            fut.result()
        except Exception as e:
            failed += 1
            print(f"  FAILED {t['session_id']}: {e}")
    for ex in executors.values():
        ex.shutdown(wait=True)
    return failed


class BatchWriter:
    def __init__(self, tag: str):
        self.tag = tag
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        existing = [p for p in OUTPUT_DIR.glob(f"{tag}_batch_*.csv") if not p.name.endswith(".tmp")]
        # Next number = highest existing batch number + 1 (never reuse a
        # number, so a deleted/partial batch cannot be overwritten by a
        # resumed run with different content).
        nums = []
        for p in existing:
            try:
                nums.append(int(p.stem.rsplit("_", 1)[1]))
            except (ValueError, IndexError):
                continue
        self.batch_num = (max(nums) + 1) if nums else 1
        self.buffer: List[Dict] = []
        self.written = 0

    def add(self, rows: List[Dict]) -> None:
        with _csv_lock:
            self.buffer.extend(rows)
            if len(self.buffer) >= FLUSH_SESSIONS * 15:
                self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        path = OUTPUT_DIR / f"{self.tag}_batch_{self.batch_num:03d}.csv"
        tmp = OUTPUT_DIR / f"{self.tag}_batch_{self.batch_num:03d}.csv.tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SESSION_SCHEMA)
            writer.writeheader()
            for rec in self.buffer:
                writer.writerow({k: rec.get(k, "") for k in SESSION_SCHEMA})
        tmp.replace(path)  # atomic: a crash leaves only the .tmp, never a partial batch
        self.written += len(self.buffer)
        print(f"  -> saved {path.name} ({len(self.buffer)} rows)")
        self.buffer = []
        self.batch_num += 1

    def finish(self) -> int:
        self.flush()
        return self.written


class ProgressReporter(threading.Thread):
    def __init__(self, total_sessions: int, tag: str):
        super().__init__(daemon=True)
        self.total = total_sessions
        self.tag = tag
        self._done = 0
        self._start = time.time()
        self.stop = False

    def tick(self, n: int = 1) -> None:
        with _progress_lock:
            self._done += n

    def run(self) -> None:
        while not self.stop and self._done < self.total:
            time.sleep(30)
            elapsed = time.time() - self._start
            with _progress_lock:
                done = self._done
            pct = done / self.total * 100 if self.total else 0
            rate = done / (elapsed / 60) if elapsed > 0 else 0
            eta = (self.total - done) / rate if rate > 0 else 0
            print(f"[{elapsed/60:.0f}m] {done}/{self.total} ({pct:.0f}%) "
                  f"~{rate:.1f} sessions/min  ETA: {eta:.0f}m  [{self.tag}]")
