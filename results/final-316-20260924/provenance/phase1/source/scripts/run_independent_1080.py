"""1080 separately prepared cases; each has its own complete fault and recovery cycle.
Run from /work in the Compose runner. Each case has its own data and fault cycle.
MW/WFR check missing-predecessor visibility, not every internal application order.
"""
import random
import signal
import hashlib
import json
import platform
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
ROOT = Path('/work')
sys.path.insert(0, str(SOURCE / 'src'))
sys.path.insert(0, str(SOURCE / 'scripts'))
from run_real_experiments import (LabControl, Trial, CassandraConfig, CassandraExecutor,
                                 PROPERTIES, LEVELS, SCENARIOS, summarize, check, Observation)

OUT = SOURCE.parent
RUN_ID = OUT.name
KEYSPACE = 'independent_1080_20260923'
CASES = []
randomizer = random.Random(5208)
for repetition in range(30):
    block = [(s, c, p) for s in SCENARIOS for c in LEVELS for p in PROPERTIES]
    randomizer.shuffle(block)
    for scenario, cl, prop in block:
        expected = ('PASS' if scenario == 'normal' or scenario == 'node_stop' and cl != 'ALL'
                    else 'VIOLATION' if scenario == 'partition' and cl == 'ONE' else 'INCONCLUSIVE')
        cid = f'{len(CASES)+1:04d}_{scenario}_{cl.lower()}_{prop}_r{repetition+1:02d}'
        CASES.append((cid, scenario, cl, prop, expected))


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n')
    temporary.replace(path)


def verify_record(record, controls, addresses):
    assert len(record['setup']) == 5
    assert all(e['status'] == 'ok' and e['version'] == 0 for e in record['setup'])
    history = record['history']
    for e in record['setup'] + history:
        assert 'mock' not in e['raw'].get('step', {})
        if e['op'] in ('read', 'write') and e['status'] == 'ok':
            assert e['raw']['coordinator'] == addresses[e['node']]
    replay = check(record['property'], [Observation(**e) for e in history])
    # Trial may mark MR/WFR inconclusive when the intended fresh prerequisite was not obtained.
    assert replay.status == record['result']['status'] or record['result']['status'] == 'INCONCLUSIVE'
    if record['scenario'] == 'partition':
        isolation = next(c for c in controls if c['op'] == 'verified_isolation' and c['node'] == 'N3')
        assert isolation['blocked_in'] and isolation['blocked_out'] and isolation['cql_tcp_reachable']
    if record['scenario'] == 'node_stop':
        assert any(c['op'] == 'stop' and c['status'] == 'stopped' for c in controls)
    for e in history:
        if e['op'] == 'dependency_probe':
            proof = next(c for c in controls if c['control_id'] == e['raw']['control_id'])
            assert proof['op'] == 'verified_isolation' and proof['node'] == 'N1'
            assert proof['blocked_in'] and proof['blocked_out']
            effect = history[e['raw']['effect_read_index']]
            cause = history[e['raw']['cause_read_index']]
            assert effect['node'] == cause['node'] == 'N1'
            assert effect['write_id'] == e['write_id'] and cause['write_id'] == e['raw']['cause_write_id']
    return True


def now():
    return datetime.now(timezone.utc).isoformat()


def run():
    if (OUT / 'plan.json').exists():
        raise RuntimeError('This pilot directory already has a run; preserve it.')
    sources = [f for f in SOURCE.rglob('*') if f.is_file() and '__pycache__' not in f.parts]
    save(OUT / 'source-hashes.json', {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    save(OUT / 'plan.json', {
        'written_before_workloads': True, 'started_at': now(),
        'seed': 5208, 'repeats_per_combination': 30, 'total_cases': 1080,
        'workload_partition_episodes': 360, 'node_stop_episodes': 360,
        'cases': [dict(zip(['case_id', 'scenario', 'consistency', 'property', 'predicted_status'], c)) for c in CASES],
        'design': '1080 cases: 36 combinations repeated 30 times in shuffled blocks. Every case has fresh unique data, preflight, its own fault injection where applicable, observations and verified recovery. One fresh run keyspace, shared table, unique case keys; containers are not recreated per case.',
        'scope': 'MW/WFR: immutable predecessor visibility at a verified local replica; PASS is not a proof of all internal execution orders.',
    })
    started = time.perf_counter()
    summaries = []
    records = []
    save(OUT / 'progress.json', {'status': 'running', 'completed': 0, 'total': len(CASES), 'started_at': now()})
    for cid, scenario, cl, prop, expected in CASES:
        folder = OUT / cid
        folder.mkdir()
        ctrl = LabControl(folder)
        db = None
        trial = None
        timings = {}
        began = time.perf_counter()
        meta = {'case_id': cid, 'started_at': now(), 'predicted_status': expected}
        failure = None
        save(OUT / 'progress.json', {'status': 'running', 'completed': len(summaries), 'total': len(CASES), 'active_case': cid, 'updated_at': now(), 'elapsed_seconds': time.perf_counter() - started})
        print(f'{now()} START {cid}', flush=True)
        try:
            stamp = time.perf_counter()
            ctrl.preflight()
            ctrl.settle_views({n: [] for n in ctrl.containers})
            config = CassandraConfig(
                keyspace=KEYSPACE,
                contact_points=(ctrl.addresses['N1'],),
                node_contact_points={n: (ip,) for n, ip in ctrl.addresses.items()},
                node_ports={n: 9042 for n in ctrl.addresses},
            )
            db = CassandraExecutor(config)
            env = {'config': asdict(config), 'python': platform.python_version(),
                   'driver': version('cassandra-driver'), 'docker_py': version('docker'),
                   'nodes': {}, 'docker_engine': ctrl.api.version()['Version']}
            for n, container in ctrl.containers.items():
                container.reload()
                row = db._session_for_step({'node': n}).execute('SELECT release_version, host_id FROM system.local').one()
                env['nodes'][n] = {'ip': ctrl.addresses[n], 'container_id': container.id,
                    'image_id': container.image.id, 'cassandra_version': row.release_version, 'host_id': str(row.host_id)}
            save(folder / 'environment.json', env)
            case = {'trial_id': cid + ':' + uuid.uuid4().hex, 'scenario': scenario,
                    'consistency': cl, 'property': prop, 'repetition': int(cid.rsplit('_r', 1)[1]) - 1}
            trial = Trial(case, db)
            trial.prepare()
            timings['preflight_and_data_seconds'] = time.perf_counter() - stamp
            stamp = time.perf_counter()
            if scenario == 'partition':
                ctrl.set_isolated('N3', True, 'workload')
                ctrl.verify_isolation('N3', 'workload')
                ctrl.settle_views({'N1': ['N3'], 'N2': ['N3'], 'N3': ['N1', 'N2']})
            elif scenario == 'node_stop':
                ctrl.stop('N3')
                ctrl.settle_views({'N1': ['N3'], 'N2': ['N3']})
            timings['fault_injection_and_settling_seconds'] = time.perf_counter() - stamp
            stamp = time.perf_counter()
            trial.workload()
            timings['workload_seconds'] = time.perf_counter() - stamp
            stamp = time.perf_counter()
            if trial.result is None:
                ctrl.set_isolated('N1', True, 'measurement')
                proof = ctrl.verify_isolation('N1', 'measurement')
                ctrl.settle_views({'N1': ['N2', 'N3']})
                trial.probe(proof['control_id'])
            timings['probe_including_isolation_seconds'] = time.perf_counter() - stamp
            result = trial.export()
            save(folder / 'history.json', result)
            controls = [json.loads(line) for line in (folder / 'controls.jsonl').read_text().splitlines()]
            meta['evidence_verified'] = verify_record(result, controls, ctrl.addresses)
            records.append(result)
            meta.update(status=result['result']['status'], reason=result['result']['reason'],
                        witness=result['result']['witness'], workload_requests=result['workload_requests'],
                        failed_workload_requests=result['failed_workload_requests'])
        except BaseException as exc:
            failure = exc
            meta.update(status='RUN_FAILED', error=repr(exc))
            if trial is not None:
                save(folder / 'partial-history.json', {'setup': trial.setup, 'history': [asdict(e) for e in trial.history]})
        finally:
            stamp = time.perf_counter()
            try:
                ctrl.restore()
                ctrl.healthy()
                ctrl.settle_views({n: [] for n in ctrl.containers})
                for n in ('N1', 'N3'):
                    if ctrl.peer_tcp(n, 'N2') != 0 or ctrl.peer_tcp('N2', n) != 0:
                        raise RuntimeError('Internode recovery check failed')
                meta['recovery_verified'] = True
            except BaseException as exc:
                failure = failure or exc
                meta['recovery_verified'] = False
                meta['recovery_error'] = repr(exc)
            finally:
                if db is not None:
                    db.close()
                ctrl.log.close()
                ctrl.api.close()
            timings['recovery_seconds'] = time.perf_counter() - stamp
            meta.update(timings=timings, total_seconds=time.perf_counter() - began, finished_at=now())
            save(folder / 'completion.json', meta)
            summaries.append(meta)
            save(OUT / 'matrix-summary.json', summarize(records))
            save(OUT / 'progress.json', {'status': 'failed' if failure else 'complete' if len(summaries) == len(CASES) else 'running', 'completed': sum(c.get('evidence_verified', False) and c.get('recovery_verified', False) for c in summaries), 'total': len(CASES), 'last_case': meta, 'updated_at': now(), 'elapsed_seconds': time.perf_counter() - started})
            save(OUT / 'summary.json', {'cases': summaries, 'elapsed_seconds': time.perf_counter() - started,
                 'completed_cases': len(summaries), 'all_cases_completed': len(summaries) == len(CASES) and failure is None})
        print(f"{now()} END {cid}: {meta['status']}, {meta['total_seconds']:.2f}s, recovery={meta['recovery_verified']}", flush=True)
        if failure is not None:
            save(OUT / 'completion.json', {'status': 'incomplete', 'error': repr(failure), 'attempted_cases': len(summaries), 'finished_at': now()})
            raise failure
    save(OUT / 'completion.json', {'status': 'complete', 'cases': len(summaries), 'elapsed_seconds': time.perf_counter() - started, 'all_evidence_verified': all(c.get('evidence_verified') for c in summaries), 'all_recoveries_verified': all(c['recovery_verified'] for c in summaries), 'finished_at': now()})
    print(json.dumps({'total_seconds': time.perf_counter() - started, 'cases': len(summaries)}), flush=True)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Signal {signum}; preserving data and attempting recovery')
    signal.signal(signal.SIGTERM, interrupted)
    run()
