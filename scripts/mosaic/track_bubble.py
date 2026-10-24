#!/usr/bin/env python3
"""Track the chat bubble that contains the WeChat-backend numbers, frame by frame.

Template = the bubble cut from a reference frame where it is fully visible. The template is cut
into 10-row horizontal strips; every textured strip is matched (TM_CCOEFF_NORMED) inside the same
column band of each frame, and each good match votes for the bubble's top y. Short strips keep
working while the bubble is only partly on screen (scrolling in / out) or partly covered by UI.
Output: JSON {frame_index: [x0, y0, x1, y1, anchor_top]} (unclipped) in video pixel coordinates (only frames with a hit),
plus gap filling / dilation over time so a missed frame can never leak the numbers.
"""
import argparse, json, subprocess, numpy as np, cv2

ap = argparse.ArgumentParser()
ap.add_argument('--video', required=True)
ap.add_argument('--ref-time', type=float, default=28.0)
ap.add_argument('--rect', default='16,86,706,220', help='bubble x0,y0,x1,y1 in the reference frame')
ap.add_argument('--start', type=float, default=17.0)
ap.add_argument('--end', type=float, default=42.0)
ap.add_argument('--pad', type=int, default=8)
ap.add_argument('--out', default='track.json')
a = ap.parse_args()

pr = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=width,height,r_frame_rate', '-of', 'json', a.video], capture_output=True, text=True).stdout)['streams'][0]
W, H = pr['width'], pr['height']; n, d = pr['r_frame_rate'].split('/'); fps = float(n) / float(d)

def grab(t):
    o = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', a.video, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True).stdout
    return np.frombuffer(o, np.uint8).reshape(H, W)

x0, y0, x1, y1 = map(int, a.rect.split(','))
ref = grab(a.ref_time)
tpl = ref[y0:y1, x0:x1]
strips = []
for r in range(0, tpl.shape[0] - 10, 5):
    s = tpl[r:r + 10]
    if s.std() > 18:            # only strips with real text texture
        strips.append((r, s))
print(f'{len(strips)} textured strips, fps {fps}')
BX0, BX1 = max(x0 - 4, 0), min(x1 + 4, W)

f0 = int(round(a.start * fps)); f1 = int(round(a.end * fps))
p = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f'{f0 / fps:.4f}', '-i', a.video, '-frames:v', str(f1 - f0),
                      '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], stdout=subprocess.PIPE)
raw = {}
i = f0
while True:
    b = p.stdout.read(W * H)
    if len(b) < W * H: break
    fr = np.frombuffer(b, np.uint8).reshape(H, W)
    band = fr[:, BX0:BX1]
    votes = []
    for r, s in strips:
        res = cv2.matchTemplate(band, s, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx > 0.85:
            votes.append(loc[1] - r)
    if votes:
        v = np.array(votes)
        # largest cluster within +-3 px
        best = max(v, key=lambda c: (np.abs(v - c) <= 3).sum())
        k = (np.abs(v - best) <= 3).sum()
        if k >= 2:
            raw[i] = (float(np.median(v[np.abs(v - best) <= 3])), int(k))
    i += 1
nfr = i
print(f'scanned frames {f0}..{nfr - 1}, hits {len(raw)}')
# gap filling: interpolate tops across short detection gaps (<= 0.2 s)
keys = sorted(raw)
tops = {k: raw[k][0] for k in keys}
for k0, k1 in zip(keys, keys[1:]):
    if 1 < k1 - k0 <= int(0.2 * fps):
        for k in range(k0 + 1, k1):
            tops[k] = tops[k0] + (tops[k1] - tops[k0]) * (k - k0) / (k1 - k0)
hgt = y1 - y0
# per-frame rectangle: exact where the frame itself was matched; interpolated frames get extra
# padding equal to the local scroll speed; at the start/end of a run, if the bubble is scrolling,
# extrapolate 2 frames by its velocity so a half-visible line entering/leaving is still covered.
def vel(k):
    for a_, b_ in ((k - 1, k + 1), (k - 1, k), (k, k + 1)):
        if a_ in tops and b_ in tops and a_ != b_: return (tops[b_] - tops[a_]) / (b_ - a_)
    return 0.0
ext = dict(tops); extra = {k: (0.0 if k in raw else abs(vel(k))) for k in tops}
for k in list(tops):
    v = vel(k)
    if abs(v) < 0.5: continue
    if k - 1 not in tops:
        for n_ in (1, 2):
            ext.setdefault(k - n_, tops[k] - v * n_); extra.setdefault(k - n_, abs(v))
    if k + 1 not in tops:
        for n_ in (1, 2):
            ext.setdefault(k + n_, tops[k] + v * n_); extra.setdefault(k + n_, abs(v))
out = {}
for k in sorted(ext):
    top = ext[k]; e = extra[k]
    rx0, rx1 = x0 - a.pad, x1 + a.pad
    ry0 = int(np.floor(top - e)) - a.pad; ry1 = int(np.ceil(top + hgt + e)) + a.pad
    if ry1 <= 0 or ry0 >= H: continue
    out[k] = [rx0, ry0, rx1, ry1, round(top - a.pad, 1)]   # unclipped; last = content-anchored top
json.dump({'fps': fps, 'raw_hits': {str(k): v for k, v in raw.items()}, 'rects': {str(k): v for k, v in out.items()}},
          open(a.out, 'w'))
ks = sorted(out)
segs = []
for k in ks:
    if segs and k == segs[-1][1] + 1: segs[-1][1] = k
    else: segs.append([k, k])
print('masked frame ranges:', [(s / fps, e / fps) for s, e in segs])
