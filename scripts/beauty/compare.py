#!/usr/bin/env python3
"""Make original | light | medium triptychs zoomed into the portrait window (and a mouth close-up)."""
import subprocess, sys, numpy as np, cv2
RAW, START = '../raw.mp4', 168.0
CX, CY, R = 845, 932, 123
def grab(path, t):
    out = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', path, '-frames:v', '1', '-f', 'image2pipe',
                          '-vcodec', 'png', '-'], capture_output=True).stdout
    return cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
def label(im, txt):
    cv2.rectangle(im, (0, 0), (im.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(im, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    return im
for t in map(float, sys.argv[1:]):
    fr = [grab(RAW, START + t), grab('sample-light.mp4', t), grab('sample-medium.mp4', t)]
    names = ['original', 'light', 'medium']
    crops = [f[CY - R:CY + R, CX - R:CX + R] for f in fr]
    big = [label(cv2.resize(c, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4), f'{n}  t={START + t:.1f}s')
           for c, n in zip(crops, names)]
    sep = np.full((big[0].shape[0], 6, 3), 255, np.uint8)
    cv2.imwrite(f'compare-{START + t:.1f}s.jpg', np.hstack([big[0], sep, big[1], sep, big[2]]), [cv2.IMWRITE_JPEG_QUALITY, 93])
    # mouth/jaw close-up (lower-centre of the face), 6x nearest+lanczos
    mx0, my0 = CX - 60, CY - 10
    m = [label(cv2.resize(f[my0:my0 + 80, mx0:mx0 + 120], None, fx=6, fy=6, interpolation=cv2.INTER_LANCZOS4), f'{n} mouth/jaw x6')
         for f, n in zip(fr, names)]
    sep = np.full((m[0].shape[0], 6, 3), 255, np.uint8)
    cv2.imwrite(f'compare-mouth-{START + t:.1f}s.jpg', np.hstack([m[0], sep, m[1], sep, m[2]]), [cv2.IMWRITE_JPEG_QUALITY, 93])
    print('wrote', t)
