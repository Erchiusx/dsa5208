"""Replay and summarize the selected 316 real histories; never contacts Cassandra."""
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from project1.checker import check
from project1.model import Observation


def main():
    out = ROOT / 'results/final-316-20260924'
    selection = json.loads((out / 'dataset-selection.json').read_text())
    summaries = json.loads((out / 'case-summaries.json').read_text())
    plan = json.loads((out / 'provenance/phase1/plan.json').read_text())
    assert selection['selected_case_ids'] == [r['case_id'] for r in plan['cases'][:316]]
    assert len(summaries) == 316
    for relative, digest in selection['original_data_sha256'].items():
        assert hashlib.sha256((out / relative).read_bytes()).hexdigest() == digest, relative
    for phase in ('phase1', 'phase2'):
        base = out / 'provenance' / phase
        for relative, digest in json.loads((base / 'source-hashes.json').read_text()).items():
            path = base / 'source' / relative.split('/source/', 1)[1]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path
    cells = defaultdict(Counter)
    phases = defaultdict(Counter)
    requests, errors, scenarios = Counter(), Counter(), Counter()
    records, deviations, ids = [], [], set()
    probes = 0
    for i, meta in enumerate(summaries, 1):
        folder = out / 'cases' / meta['case_id']
        record = json.loads((folder / 'history.json').read_text())
        env = json.loads((folder / 'environment.json').read_text())
        controls = [json.loads(line) for line in (folder / 'controls.jsonl').read_text().splitlines()]
        assert meta['case_id'] == selection['selected_case_ids'][i-1]
        assert meta['evidence_verified'] and meta['recovery_verified']
        assert record['trial_id'] not in ids
        ids.add(record['trial_id'])
        assert len(record['setup']) == 5
        for event in record['setup'] + record['history']:
            assert 'mock' not in event['raw'].get('step', {})
            if event['op'] in ('write', 'read') and event['status'] == 'ok':
                assert event['raw']['coordinator'] == env['nodes'][event['node']]['ip']
        assert all(e['status'] == 'ok' and e['version'] == 0 for e in record['setup'])
        replay = check(record['property'], [Observation(**e) for e in record['history']])
        assert replay.status == record['result']['status'] == meta['status']
        assert replay.witness == record['result']['witness']
        if record['scenario'] == 'partition':
            assert any(c['op'] == 'verified_isolation' and c['node'] == 'N3'
                       and c['blocked_in'] and c['blocked_out'] and c['cql_tcp_reachable'] for c in controls)
        if record['scenario'] == 'node_stop':
            assert any(c['op'] == 'stop' and c['status'] == 'stopped' for c in controls)
        assert any(c['op'] == 'verified_membership' and c['expected_down'] == {'N1': [], 'N2': [], 'N3': []}
                   and c['time_ns'] > max(e['raw'].get('started_ns', 0) for e in record['history']) for c in controls)
        for event in record['history']:
            if event['op'] in ('read', 'write'):
                phase = event['raw']['phase']
                requests[phase + ':' + event['status']] += 1
                if event['status'] != 'ok':
                    errors[phase + ':' + event['raw'].get('error_type', 'unknown')] += 1
            if event['op'] == 'dependency_probe':
                probes += 1
                proof = next(c for c in controls if c['control_id'] == event['raw']['control_id'])
                assert proof['op'] == 'verified_isolation' and proof['node'] == 'N1'
                assert proof['blocked_in'] and proof['blocked_out'] and proof['cql_tcp_reachable']
                effect = record['history'][event['raw']['effect_read_index']]
                cause = record['history'][event['raw']['cause_read_index']]
                assert effect['status'] == cause['status'] == 'ok'
                assert effect['node'] == cause['node'] == 'N1'
                assert effect['write_id'] == event['write_id'] and cause['write_id'] == event['raw']['cause_write_id']
        status = meta['status']
        cells[(record['scenario'], record['consistency'], record['property'])][status] += 1
        phases['phase1' if i <= 93 else 'phase2'][status] += 1
        scenarios[record['scenario']] += 1
        if status != meta['predicted_status']:
            deviations.append({'case_id': meta['case_id'], 'predicted': meta['predicted_status'], 'observed': status})
        records.append(record)
    matrix = [dict(zip(['scenario', 'consistency', 'property'], cell),
                   trials=sum(counts.values()), **{k: counts[k] for k in ('PASS','VIOLATION','INCONCLUSIVE')})
              for cell, counts in sorted(cells.items())]
    assert len(matrix) == 36 and set(row['trials'] for row in matrix) == {8, 9}
    result = {'valid': True, 'histories': len(records), 'cells': 36,
              'trials_per_cell': dict(Counter(row['trials'] for row in matrix)),
              'statuses': dict(Counter(m['status'] for m in summaries)),
              'scenarios': dict(scenarios), 'phases': dict(phases), 'requests': dict(requests),
              'request_errors': dict(errors), 'successful_setup_requests': 5 * len(records),
              'verified_local_probes': probes, 'prediction_deviations': deviations,
              'source_and_data_hashes_verified': True,
              'scope': 'Selected completed subset; original 1080-case target was not completed.'}
    for name, value in [('matrix-summary.json', matrix), ('audit.json', result)]:
        (out / name).write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
