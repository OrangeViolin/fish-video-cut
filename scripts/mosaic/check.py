"""Side-by-side mosaic check frames. Source root is $FISH_VIDEO (default video-01).

The "after" paths stay relative to the current working directory.
"""
import os, subprocess, numpy as np, cv2, sys
ROOT = os.environ.get('FISH_VIDEO', 'video-01')
def grab(p, t):
    o = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', p, '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True).stdout
    return cv2.imdecode(np.frombuffer(o, np.uint8), 1)
def lab(im, t):
    cv2.rectangle(im, (0, 0), (im.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(im, t, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA); return im
pairs = [(os.path.join(ROOT, 'out/final.mp4'), 'full/final-mosaic.mp4', 'sub'),
         (os.path.join(ROOT, 'out/final-nosub.mp4'), 'full/final-mosaic-nosub.mp4', 'nosub')]
args = sys.argv[1:]
if args and args[0] == '--shotcraft':
    args = args[1:]
    pairs = [(os.path.join(ROOT, 'shotcraft/final-shotcraft.mp4'), 'full/final-shotcraft-mosaic.mp4', 'shotcraft-sub'),
             (os.path.join(ROOT, 'shotcraft/final-shotcraft-nosub.mp4'), 'full/final-shotcraft-mosaic-nosub.mp4', 'shotcraft-nosub')]
for t in map(float, args):
    for a, b, tag in pairs:
        A = lab(grab(a, t), f'before ({tag}) t={t:.2f}s'); B = lab(grab(b, t), f'after ({tag}) t={t:.2f}s')
        sep = np.full((A.shape[0], 8, 3), 255, np.uint8)
        cv2.imwrite(f'mosaic-check-{t:.2f}s-{tag}.jpg', np.hstack([A, sep, B]), [cv2.IMWRITE_JPEG_QUALITY, 90])
