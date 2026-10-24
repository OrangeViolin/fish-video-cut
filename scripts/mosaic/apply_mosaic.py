#!/usr/bin/env python3
"""Burn a strong mosaic + Gaussian blur over tracked rectangles, then (optionally) subtitles on top.

One decode, two encodes: --out-nosub (mosaic only) and --out-sub (mosaic, then ASS subtitles burned
*after* the mosaic, so subtitles stay sharp). Audio is copied from --audio-from.
"""
import argparse, json, subprocess, numpy as np, cv2

ap = argparse.ArgumentParser()
ap.add_argument('--video', required=True)
ap.add_argument('--track', required=True)
ap.add_argument('--audio-from', required=True)
ap.add_argument('--out-nosub', required=True)
ap.add_argument('--out-sub')
ap.add_argument('--ass')
ap.add_argument('--block', type=int, default=16, help='mosaic block size (px)')
ap.add_argument('--sigma', type=float, default=10.0, help='gaussian blur sigma applied before and after pixelation')
ap.add_argument('--crf', type=int, default=16)
ap.add_argument('--clip-bottom', type=int, default=None, help='never censor below this y (e.g. the chat input bar, which hides the chat underneath)')
a = ap.parse_args()

pr = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=width,height,r_frame_rate', '-of', 'json', a.video], capture_output=True, text=True).stdout)['streams'][0]
W, H, R = pr['width'], pr['height'], pr['r_frame_rate']
rects = {int(k): v for k, v in json.load(open(a.track))['rects'].items()}

def censor(fr, r):
    x0, y0, x1, y1, anchor = r
    BOT = min(H, a.clip_bottom) if a.clip_bottom else H
    cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, BOT)
    if cx1 <= cx0 or cy1 <= cy0: return
    # work on the full (unclipped) rect so the mosaic grid is anchored to the content and scrolls with it
    pad_top = cy0 - y0; pad_bot = y1 - cy1
    reg = fr[cy0:cy1, cx0:cx1]
    reg = cv2.copyMakeBorder(reg, pad_top, pad_bot, 0, 0, cv2.BORDER_REPLICATE)
    b = cv2.GaussianBlur(reg, (0, 0), a.sigma)
    h, w = b.shape[:2]; B = a.block
    small = cv2.resize(b, (max(1, w // B), max(1, h // B)), interpolation=cv2.INTER_AREA)
    mos = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    mos = cv2.GaussianBlur(mos, (0, 0), 2.0)          # soften block edges a little
    mos = mos[pad_top:pad_top + (cy1 - cy0)]
    # feathered edge (only on edges that lie inside the frame); text area always 100% covered
    hh, ww = cy1 - cy0, cx1 - cx0
    m = np.zeros((hh, ww), np.float32)
    t0 = 0 if pad_top or cy0 == 0 else 3
    b0 = hh if pad_bot or cy1 == BOT else hh - 3
    m[t0:b0, 3:ww - 3] = 1
    m = cv2.GaussianBlur(m, (0, 0), 1.5)
    m[(0 if t0 == 0 else 6):(hh if b0 == hh else hh - 6), 6:ww - 6] = 1
    fr[cy0:cy1, cx0:cx1] = (reg[pad_top:pad_top + (cy1 - cy0)] * (1 - m[..., None]) + mos * m[..., None]).astype(np.uint8)

def enc(out, vf=None):
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', R, '-i', '-',
           '-i', a.audio_from, '-map', '0:v', '-map', '1:a', '-c:a', 'copy']
    if vf: cmd += ['-vf', vf]
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', str(a.crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)

dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', a.video, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
encs = [enc(a.out_nosub)]
if a.out_sub:
    encs.append(enc(a.out_sub, f"ass={a.ass}"))
n = W * H * 3; i = 0; hit = 0
while True:
    b = dec.stdout.read(n)
    if len(b) < n: break
    fr = np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()
    if i in rects:
        censor(fr, rects[i]); hit += 1
    for e in encs: e.stdin.write(fr.tobytes())
    i += 1
for e in encs: e.stdin.close(); e.wait()
print(json.dumps({'frames': i, 'censored_frames': hit}))
