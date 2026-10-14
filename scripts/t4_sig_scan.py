#!/usr/bin/env python3
"""Read-only scan of t4_audit_summary.txt: every per-cell comparison where per-feature is the first method, sorted into
significantly better (rel < 0, p < 0.05) and significantly worse (rel > 0, p < 0.05); the rest are not significant.
Usage: ~/navcore_ws/.venv/bin/python scripts/t4_sig_scan.py ~/navcore_ws/results/t4_audit_summary.txt"""
import re, sys
block, cell, metric, rows = '', '?', '?', []
for s in (l.rstrip('\n') for l in open(sys.argv[1])):
    if s.startswith('====='): block = 'P7b euroc' if 'P7b' in s else ('P8' if 'P8' in s else '')
    b = re.match(r'^\s+-- (.*)$', s)
    if b: block = b.group(1).replace('T.3b grid, udel_gore, ', 'grid ').replace(' (f 0.5, 250 pts)', '')
    h = re.match(r'^\s+((?:sigma_bad|f |[A-Za-z_0-9]+, sigma_bad)[^:]*):', s)
    if h and '[' not in s: cell = h.group(1).strip()
    if re.search(r'\bpos \(m\):', s): metric = 'pos'
    if re.search(r'\bori \(deg\):', s): metric = 'ori'
    m = re.search(r'\[perfeat@1\.5 vs ([^\]]+)\] ([+-]\d+\.\d)% \[\+-[\d.]+%\] p=([\d.e+-]+)', s)
    if m and 'overall' not in s: rows.append((f'{block}: {cell}', metric, m.group(1), float(m.group(2)), float(m.group(3))))
for title, keep in (('significantly better', lambda r, p: r < 0 and p < 0.05), ('significantly WORSE', lambda r, p: r > 0 and p < 0.05)):
    sel = [x for x in rows if keep(x[3], x[4])]
    print(f'per-feature {title}: {len(sel)} of {len(rows)} per-cell comparisons')
    for c, mt, vs, r, p in sel: print(f'   {c:52s} {mt}  vs {vs:12s} {r:+6.1f}%  p={p:.1e}')
