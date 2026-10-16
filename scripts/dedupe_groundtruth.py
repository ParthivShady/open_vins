#!/usr/bin/env python3
"""Replace identical copies of state_groundtruth.txt under ~/navcore_ws/results with hard links to one copy each,
and make the shared copies read-only, so no later run can write into them through a link.
Usage:  python3 dedupe_groundtruth.py           dry run: reports what it would free, changes nothing
        python3 dedupe_groundtruth.py --apply   does it
Every path stays in place with the same bytes, so all scripts read exactly what they read before.
Refuses to run while a batch or the simulator is running. Re-runs must go into a fresh folder, as the batch
scripts already do (they delete the run folder first); a run written over an existing linked file would now fail
to open it, instead of silently changing every linked copy."""
import hashlib, os, shutil, subprocess, sys
from collections import defaultdict

RES = os.path.expanduser(os.environ.get('NAVCORE_RES', '~/navcore_ws/results'))
NAME = 'state_groundtruth.txt'
APPLY = '--apply' in sys.argv
busy = subprocess.run(['pgrep', '-f', 'run_t4d_g1_batch|run_t4_audit_batch|run_simulation'], capture_output=True).returncode == 0
if busy and not os.environ.get('NAVCORE_DEDUPE_TEST'):
    sys.exit('a batch or the simulator is running; run this after it finishes. Nothing changed.')

def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

by_size = defaultdict(list)
for dp, _, fn in os.walk(RES):
    if NAME in fn:
        p = os.path.join(dp, NAME)
        if not os.path.islink(p):
            by_size[os.stat(p).st_size].append(p)
n = sum(len(v) for v in by_size.values())
groups = defaultdict(list)
for size, ps in by_size.items():
    if len(ps) == 1:
        groups[(size, None)] = ps
    else:
        for p in ps:
            groups[(size, md5(p))].append(p)
free0 = shutil.disk_usage(RES).free
linked = already = freed = 0
for (size, h), ps in groups.items():
    if len(ps) < 2:
        continue
    ps.sort()
    keep = ps[0]
    k = os.stat(keep)
    for p in ps[1:]:
        s = os.stat(p)
        if (s.st_ino, s.st_dev) == (k.st_ino, k.st_dev):
            already += 1
            continue
        if APPLY:
            tmp = p + '.navcore_link_tmp'
            if os.path.lexists(tmp):
                os.remove(tmp)
            os.link(keep, tmp)
            os.replace(tmp, p)       # atomic: the path never disappears
        linked += 1
        freed += size
    if APPLY:
        os.chmod(keep, 0o444)        # shared by every link
verb = 'linked' if APPLY else 'would link'
print(f'{n} ground-truth files, {len(groups)} distinct contents; {verb} {linked} copies, freeing {freed / 1e9:.2f} GB'
      f'{f"; {already} were already linked" if already else ""}.')
if APPLY:
    print(f'free space: {free0 / 1e9:.1f} GB before, {shutil.disk_usage(RES).free / 1e9:.1f} GB after')
else:
    print('dry run: nothing changed. Run again with --apply to do it.')
