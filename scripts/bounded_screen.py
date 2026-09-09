#!/usr/bin/env python3
"""Process-isolated, checkpointed wrapper for the existing read-only V2/V3 screen.

A dead provider cannot hold the whole process open indefinitely. All providers are
allowed the same bounded window; incomplete captures never vote. Any disagreement
between complete captures rejects the result, even when a majority agrees.
"""
import argparse
import datetime as dt
import functools
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

import v3_market_screen as v
from screen_integrity import audit_screen
from rpc_transport import SafeTransportError

MAX_SECONDS = 120.0
MAX_DOCUMENT = 4 * 1024 * 1024
CODE = re.compile(r'[A-Z][A-Z0-9_]{2,79}\Z')


def atomic_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    temporary.write_text(json.dumps(document, sort_keys=True, indent=2) + '\n')
    os.replace(temporary, path)


def safe_code(exc):
    text = str(exc)
    return text if isinstance(exc, (ValueError, SafeTransportError)) and CODE.fullmatch(text) else 'CAPTURE_FAILED'


class JournalReader(v.Reader):
    """Flush one sanitized request/result file per batch, before starting the next."""
    def __init__(self, label, ref, *, directory):
        super().__init__(label, ref)
        self.directory = Path(directory)
        self.batch = 0

    def read(self, calls):
        # Keep the original method and total-call limits before splitting batches.
        if self.count + len(calls) > v.MAX_CALLS:
            raise ValueError('CALL_BUDGET')
        if any(m not in {'eth_call', 'eth_getCode'} or m not in v.ALLOWED for m, _ in calls):
            raise ValueError('READ_ONLY_POLICY')
        result = []
        for offset in range(0, len(calls), 12):
            chunk = calls[offset:offset+12]
            self.batch += 1
            start = time.monotonic()
            # Only local allowlisted RPC methods and their fixed public-state params.
            note = dict(provider=self.label, batch=self.batch, status='RUNNING',
                        calls_before=self.count, count=len(chunk), requests=chunk,
                        captured_at=dt.datetime.now(dt.timezone.utc).isoformat())
            filename = self.directory / ('batch-%03d.json' % self.batch)
            atomic_json(filename, note)
            atomic_json(self.directory/'progress.json', note)
            try:
                part = super().read(chunk)
                note.update(status='COMPLETE', results=part, elapsed_seconds=round(time.monotonic()-start, 3))
                atomic_json(filename, note)
                atomic_json(self.directory/'progress.json', note)
                result.extend(part)
            except Exception as exc:
                note.update(status='FAILED', failure_code=safe_code(exc),
                            elapsed_seconds=round(time.monotonic()-start, 3))
                atomic_json(filename, note)
                atomic_json(self.directory/'progress.json', note)
                raise
        return result


def capture_worker(label, quorum_path, output, token):
    result = dict(status='FAILED', provider=label, token=token, execution_allowed=False, realized_pnl='0')
    try:
        q, qd = v.validate_quorum(json.loads(Path(quorum_path).read_text()), time.time())
        if label not in q['state_voters']:
            raise ValueError('PROVIDER_NOT_IN_QUORUM')
        # Only the child process replaces its Reader; the pricing algorithm is unchanged.
        v.Reader = functools.partial(JournalReader, directory=Path(output).parent/'batches')
        value = v.capture(label, q)
        v.validate_quorum(json.loads(Path(quorum_path).read_text()), time.time())
        result.update(status='PASS', observation=value, quorum_sha256=qd)
    except Exception as exc:
        result.update(failure_code=safe_code(exc), failure_type=type(exc).__name__)
    atomic_json(output, result)
    return 0 if result['status'] == 'PASS' else 1


def stop_children(children):
    for process in children:
        if process.poll() is None:
            process.terminate()
    for process in children:
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def run_workers(commands, root, token, *, timeout=MAX_SECONDS):
    """Start at most four trusted local commands, enforce one wall-clock deadline.

    Internal commands come only from main() or local tests, never from an RPC.
    Files written before a timeout remain evidence of a PARTIAL capture, not votes.
    """
    if not 0 < timeout <= MAX_SECONDS or not 2 <= len(commands) <= 4:
        raise ValueError('WORKER_LIMIT')
    if len(set(commands)) != len(commands) or any(not re.fullmatch(r'[a-z0-9-]{1,40}', k) for k in commands):
        raise ValueError('WORKER_LABEL')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    jobs, records, streams = {}, {}, []
    started = time.monotonic()
    deadline = started + timeout
    try:
        for label, command in commands.items():
            d = root/label
            d.mkdir(exist_ok=False)  # Never accept stale results from an older attempt.
            stream = (d/'worker.log').open('w')
            streams.append(stream)
            jobs[label] = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream)
        while len(records) < len(jobs):
            for label, process in jobs.items():
                if label in records or process.poll() is None:
                    continue
                code = process.returncode
                entry = dict(status='FAILED', returncode=code, failure_code='WORKER_EXIT_OR_DOCUMENT')
                p = root/label/'result.json'
                try:
                    if p.stat().st_size > MAX_DOCUMENT:
                        raise ValueError('WORKER_DOCUMENT_SIZE')
                    doc = json.loads(p.read_text())
                    if doc.get('provider') != label or doc.get('token') != token:
                        raise ValueError('WORKER_RESULT_IDENTITY')
                    if code == 0 and doc.get('status') == 'PASS' and isinstance(doc.get('observation'), dict):
                        entry = dict(status='PASS', returncode=code, result=doc)
                    elif isinstance(doc.get('failure_code'), str) and CODE.fullmatch(doc['failure_code']):
                        entry['failure_code'] = doc['failure_code']
                except (OSError, ValueError, AttributeError, TypeError):
                    pass
                records[label] = entry
                atomic_json(root/'supervisor.json', dict(status='RUNNING', workers=records, token=token))
            if len(records) == len(jobs):
                break
            if time.monotonic() >= deadline:
                for label in jobs.keys()-records.keys():
                    records[label] = dict(status='DEADLINE', failure_code='PROVIDER_DEADLINE', partial_capture=True)
                break
            time.sleep(0.03)
    finally:
        stop_children(list(jobs.values()))
        for stream in streams:
            stream.close()
        summary = dict(status='FINISHED', workers=records, token=token,
                       elapsed_seconds=round(time.monotonic()-started, 3),
                       timeout_seconds=timeout, all_children_reaped=all(p.poll() is not None for p in jobs.values()),
                       execution_allowed=False, realized_pnl='0')
        atomic_json(root/'supervisor.json', summary)
    return summary


def strict_agreement(observations):
    if len(observations) < 2:
        raise ValueError('INSUFFICIENT_COMPLETE_PROVIDERS')
    if len({v.digest(x) for x in observations.values()}) != 1:
        raise ValueError('COMPLETE_PROVIDER_CONFLICT')
    return observations[sorted(observations)[0]], sorted(observations)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--quorum', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--worker', choices=tuple(v.PROVIDERS))
    ap.add_argument('--token', default='')
    args = ap.parse_args()
    if args.worker:
        return capture_worker(args.worker, args.quorum, args.out, args.token)
    report = dict(schema='flash.v2_v3_quote_screen.v1', status='FAILED', execution_allowed=False,
                  realized_pnl='0', exact_arbitrum_fee_known=False, fork_execution_verified=False,
                  total_market_coverage=False, runtime_hashes_preapproved=False,
                  quote_gas_used_as_total_fee=False, source_commit=os.getenv('GITHUB_SHA'),
                  run_id=os.getenv('GITHUB_RUN_ID'), started_at=dt.datetime.now(dt.timezone.utc).isoformat())
    atomic_json(args.out, report)
    try:
        q, qd = v.validate_quorum(json.loads(args.quorum.read_text()), time.time())
        root = Path(tempfile.mkdtemp(prefix='providers-', dir=args.out.parent)).resolve()
        token = root.name
        commands = {label: [sys.executable, str(Path(__file__).resolve()), '--worker', label,
                           '--quorum', str(args.quorum.resolve()), '--out', str(root/label/'result.json'), '--token', token]
                    for label in q['state_voters']}
        supervisor = run_workers(commands, root, token)
        complete, errors = {}, {}
        for label, row in supervisor['workers'].items():
            if row['status'] == 'PASS' and row['result'].get('quorum_sha256') == qd:
                complete[label] = row['result']['observation']
            else:
                errors[label] = dict(status=row['status'], failure_code=row.get('failure_code', 'WORKER_SOURCE_MISMATCH'))
        report.update(provider_failures=errors, complete_providers=sorted(complete),
                      provider_diagnostics_directory=root.name, capture_elapsed_seconds=supervisor['elapsed_seconds'])
        value, voters = strict_agreement(complete)
        v.validate_quorum(json.loads(args.quorum.read_text()), time.time())
        rows = value['quote_rows']
        valid = [r for r in rows if 'gross_before_gas_wei' in r]
        positive = [r for r in valid if int(r['gross_before_gas_wei']) > 0]
        report.update(block_number=q['block_number'], header=q['header'], quorum_sha256=qd,
                      voters=voters, observations=value, rows_requested=len(rows), successful_quotes=len(valid),
                      unavailable_quotes=len(rows)-len(valid), positive_before_gas=len(positive),
                      top_quotes=sorted(valid, key=lambda r: int(r['gross_before_gas_wei']), reverse=True)[:10],
                      decision='CANDIDATES_NEED_ATOMIC_FORK_AND_FEES' if positive else 'NO_PROFITABLE_QUOTE_IN_SUCCESSFUL_SUBSET')
        report['accounting_check'] = audit_screen(q, report)
        report['status'] = 'PASS'
    except Exception as exc:
        report.update(failure_type=type(exc).__name__, failure_code=safe_code(exc))
    report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    report['sha256'] = v.digest(report)
    atomic_json(args.out, report)
    print(v.canonical({k: report[k] for k in ('status', 'rows_requested', 'successful_quotes', 'positive_before_gas', 'failure_code') if k in report}), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    # Let the finally block reap all network workers on an outer supervisor timeout.
    def interrupt(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    raise SystemExit(main())
