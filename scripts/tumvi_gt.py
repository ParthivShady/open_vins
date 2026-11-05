#!/usr/bin/env python3
"""NavCore: TUM-VI ground truth for the evaluation.
Usage:  ~/navcore_ws/.venv/bin/python scripts/tumvi_gt.py <bag (ROS 1 .bag or ROS 2 folder)> <out.csv>
Reads the motion-capture poses (/vrpn_client/raw_transform, geometry_msgs/TransformStamped) from a *calibrated* TUM-VI
bag, where they are already expressed for the IMU frame and synchronised to IMU time, and writes them in the EuRoC
ground-truth format that t4d_euroc_eval.py reads: timestamp [ns], p x y z [m], q w x y z.
Stops with an error if the topic is missing or holds too few poses."""
import sys
from pathlib import Path
from rosbags.highlevel import AnyReader
from rosbags.typesys import Stores, get_typestore

TOPIC = '/vrpn_client/raw_transform'
if len(sys.argv) != 3:
    sys.exit(__doc__)
bag, out = Path(sys.argv[1]), Path(sys.argv[2])
rows = []
with AnyReader([bag], default_typestore=get_typestore(Stores.ROS2_HUMBLE)) as reader:
    conns = [c for c in reader.connections if c.topic == TOPIC]
    if not conns:
        sys.exit(f'no {TOPIC} topic in {bag}; topics: {sorted({c.topic for c in reader.connections})}')
    for conn, _, raw in reader.messages(connections=conns):
        m = reader.deserialize(raw, conn.msgtype)
        t = m.header.stamp.sec * 1_000_000_000 + m.header.stamp.nanosec
        p, q = m.transform.translation, m.transform.rotation
        rows.append((t, p.x, p.y, p.z, q.w, q.x, q.y, q.z))
rows.sort()
if len(rows) < 100:
    sys.exit(f'only {len(rows)} poses on {TOPIC}; is this a calibrated TUM-VI bag?')
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, 'w') as f:
    f.write('#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z []\n')
    for r in rows:
        f.write(f'{r[0]},{r[1]:.6f},{r[2]:.6f},{r[3]:.6f},{r[4]:.9f},{r[5]:.9f},{r[6]:.9f},{r[7]:.9f}\n')
dur = (rows[-1][0] - rows[0][0]) * 1e-9
print(f'{out}: {len(rows)} poses over {dur:.1f} s ({len(rows) / dur:.0f} Hz)')
