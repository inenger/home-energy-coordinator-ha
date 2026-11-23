#!/usr/bin/env python3
"""Check that version-locked SolaX source patch is only four monitored insertions.

The upstream vendor file is intentionally *not* in this repository.
"""
from pathlib import Path
import re,sys,hashlib

root=Path(__file__).resolve().parents[1]/'ops/solax_modbus'
patch=(root/'solax_2026.11.04_interval_diagnostics.patch').read_text()
readme=(root/'README.md').read_text()
expected=[
    '',
    'from .poll_interval_monitor import PollIntervalMonitor',
    '        self._comm_interval_monitor = PollIntervalMonitor()',
    '        self._comm_interval_monitor.record(interval, elapsed, outcome.communication_succeeded)',
    '            "poll_interval_diagnostics": self._comm_interval_monitor.snapshot(self.config),',
]
lines=patch.splitlines()
assert lines[:2]==['--- a/__init__.py','+++ b/__init__.py']
assert len([x for x in lines if x.startswith('@@ ')])==4
assert [x[1:] for x in lines if x.startswith('+') and not x.startswith('+++')]==expected
assert not any(x.startswith('-') and not x.startswith('---') for x in lines)
assert '376ba1abf0d85f18f444e2521426812344c67d169d8b1870790948124781b53c' in readme
assert '9507d55ef4226eea8ca00007cdc17a9e8031f0cebd195fc73a1aa976f249c7a0' in readme
assert '1 s' in readme and '5 s' in readme
print('SolaX version-locked four-hunk read-only instrumentation patch PASS')


# Optional read-only end-to-end check against a privately held *original*
# vendor __init__.py, never vendor data in Git or a write to HA.
if len(sys.argv)>1:
    original=Path(sys.argv[1]).read_text()
    assert hashlib.sha256(original.encode()).hexdigest()=='376ba1abf0d85f18f444e2521426812344c67d169d8b1870790948124781b53c'
    old=original.splitlines(keepends=True)
    out=[];cursor=0;current=None
    for line in patch.splitlines(keepends=True)[2:]:
        if line.startswith('@@ '):
            match=re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@',line)
            assert match, line
            pos=int(match.group(1))-1
            assert pos>=cursor
            out.extend(old[cursor:pos]);cursor=pos
        elif line.startswith(' '):
            assert old[cursor]==line[1:],(cursor,line[:80])
            out.append(old[cursor]);cursor+=1
        elif line.startswith('-'):
            assert old[cursor]==line[1:],(cursor,line[:80])
            cursor+=1
        elif line.startswith('+'):
            out.append(line[1:])
        else:
            raise AssertionError('Unknown diff line: '+line[:100])
    out.extend(old[cursor:])
    transformed=''.join(out)
    assert hashlib.sha256(transformed.encode()).hexdigest()=='9507d55ef4226eea8ca00007cdc17a9e8031f0cebd195fc73a1aa976f249c7a0'
    print('SolaX four-hunk patch against exact original verified, target SHA PASS (no files changed)')
