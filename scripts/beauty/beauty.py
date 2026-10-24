#!/usr/bin/env python3
"""Deterministic face beautification for a circular picture-in-picture talking-head overlay.

Pipeline (per frame, ROI only, pasted back into the untouched full frame):
  1. MediaPipe FaceLandmarker (VIDEO mode) on a 2x-upscaled crop of the round overlay.
  2. One Euro filter on all 478 landmarks (separate params for contour / lips), presence fade
     when the face is lost, yaw-based attenuation for turned heads.
  3. Face slimming: smooth displacement field built from the lower face-oval landmarks
     (cheek -> jaw angle -> chin taper), pushed toward the facial midline, fast fall-off outside
     the face so background lines are left (nearly) untouched; applied with cv2.remap.
  4. Teeth: inner-lip polygon mask x brightness/low-redness teeth mask; LAB de-yellow + lift,
     grey-level closing + bilateral smoothing for gaps; optional very small vertical warp that
     pulls the upper incisal edge toward a fitted smooth curve (temporally smoothed).
  5. Skin: guided-filter frequency separation (keeps fine texture) on face mask minus eyes/brows/lips.

No generative model is used anywhere.

Example:
  python beauty.py --input raw.mp4 --output out.mp4 --start 168 --duration 6 \
      --slim 0.03 --teeth 0.5 --smooth 0.25
"""
import argparse, subprocess, time, sys, os, json
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- MediaPipe landmark index sets ----------
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400,
             377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
# lower contour, from ear-level cheek down to (excluding) chin, both sides
SIDE_R = [454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152]
SIDE_L = [234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152]
SIDE_W = [0.25, 0.55, 0.85, 1.0, 1.0, 0.9, 0.7, 0.45, 0.2, 0.05, 0.0]
INNER_LIP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
OUTER_LIP = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
L_EYE = [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7]
R_EYE = [263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249]
L_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
R_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LIP_IDX = sorted(set(INNER_LIP + OUTER_LIP + [0, 13, 14, 17, 37, 39, 40, 61, 267, 269, 270, 291, 84, 91, 146, 181, 314, 321, 375, 405]))


# ---------- One Euro filter ----------
class OneEuro:
    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.mc, self.beta, self.dc = np.asarray(min_cutoff, np.float64), beta, d_cutoff
        self.x = None; self.dx = None

    @staticmethod
    def _a(cut, dt):
        tau = 1.0 / (2 * np.pi * cut)
        return 1.0 / (1.0 + tau / dt)

    def reset(self):
        self.x = None

    def __call__(self, x, dt):
        if self.x is None:
            self.x = x.copy(); self.dx = np.zeros_like(x); return x.copy()
        dx = (x - self.x) / dt
        ad = self._a(self.dc, dt)
        self.dx = ad * dx + (1 - ad) * self.dx
        cut = self.mc + self.beta * np.abs(self.dx)
        a = self._a(cut, dt)
        self.x = a * x + (1 - a) * self.x
        return self.x.copy()


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def poly_mask(shape, pts, ss=8):
    """Anti-aliased filled polygon mask in [0,1] (subpixel via fillPoly shift)."""
    m = np.zeros(shape, np.uint8)
    p = np.round(np.asarray(pts) * ss).astype(np.int32)
    cv2.fillPoly(m, [p], 255, lineType=cv2.LINE_AA, shift=int(np.log2(ss)))
    return m.astype(np.float32) / 255.0


def guided_filter(I, p, r, eps):
    """Gray guide I, input p (float32, 0..1)."""
    k = (2 * r + 1, 2 * r + 1)
    mI = cv2.boxFilter(I, -1, k); mp_ = cv2.boxFilter(p, -1, k)
    cIp = cv2.boxFilter(I * p, -1, k) - mI * mp_
    vI = cv2.boxFilter(I * I, -1, k) - mI * mI
    a = cIp / (vI + eps); b = mp_ - a * mI
    return cv2.boxFilter(a, -1, k) * I + cv2.boxFilter(b, -1, k)


# ---------- ROI detection ----------
def detect_circle(path, times=(5, 30, 60, 90, 120, 150)):
    cands = []
    for t in times:
        r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', path, '-frames:v', '1',
                            '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True)
        if not r.stdout: continue
        im = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_GRAYSCALE)
        H, W = im.shape
        g = cv2.medianBlur(im, 5)
        c = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, 1.2, 100, param1=100, param2=40,
                             minRadius=int(min(H, W) * 0.06), maxRadius=int(min(H, W) * 0.2))
        if c is not None:
            cands.append(c[0][0])
    if not cands:
        raise SystemExit('could not auto-detect the round portrait window; pass --roi cx,cy,r')
    c = np.median(np.array(cands), axis=0)
    return int(round(c[0])), int(round(c[1])), int(round(c[2]))


# ---------- the per-face processor ----------
class Beautifier:
    def __init__(self, S, slim, teeth, smooth, bite, fps, model):
        import mediapipe as mp
        from mediapipe.tasks.python import vision, BaseOptions
        self.mp = mp
        self.S, self.slim, self.teeth, self.smooth, self.bite, self.fps = S, slim, teeth, smooth, bite, fps
        self.lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model), running_mode=vision.RunningMode.VIDEO,
            num_faces=1, min_face_detection_confidence=0.5, min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5))
        mc = np.full((478, 2), 1.2); mc[LIP_IDX] = 4.0          # lips must follow speech
        self.filt = OneEuro(mc, beta=0.25)
        self.P = None; self.presence = 0.0; self.miss = 0
        self.teeth_w = 0.0; self.bite_prof = None; self.teeth_stats = None
        self.yy, self.xx = np.mgrid[0:S, 0:S].astype(np.float32)
        self.frame_i = 0
        self.debug = {}

    def landmarks(self, crop_rgb):
        S = self.S
        up = cv2.resize(crop_rgb, (S * 2, S * 2), interpolation=cv2.INTER_CUBIC)
        res = self.lm.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                                                     data=np.ascontiguousarray(up)),
                                       int(self.frame_i * 1000 / self.fps))
        dt = 1.0 / self.fps
        if res.face_landmarks:
            P = np.array([[q.x, q.y] for q in res.face_landmarks[0]], np.float64) * S
            if self.miss > int(0.3 * self.fps):
                self.filt.reset()                 # long gap: snap, presence ramp hides the jump
            self.miss = 0
            self.P = self.filt(P, dt)
            target = 1.0
        else:
            self.miss += 1
            target = 0.0                           # hold last landmarks, fade effect out
        # presence ramps over ~0.25 s in both directions -> no popping
        step = dt / 0.25
        self.presence = float(np.clip(self.presence + np.clip(target - self.presence, -step, step), 0, 1))

    # ---- face slimming ----
    def slim_field(self, P, amt):
        S = self.S
        fw = np.linalg.norm(P[234] - P[454])
        top, chin = P[10], P[152]
        axis = (chin - top) / (np.linalg.norm(chin - top) + 1e-6)
        ctrl, disp = [], []
        for side in (SIDE_R, SIDE_L):
            pts = P[side]
            # densify contour (x4) for a smooth field
            for i in range(len(pts) - 1):
                for t in np.linspace(0, 1, 4, endpoint=False):
                    c = pts[i] * (1 - t) + pts[i + 1] * t
                    w = SIDE_W[i] * (1 - t) + SIDE_W[i + 1] * t
                    # vector to midline (perpendicular to face axis)
                    v = c - top; perp = v - np.dot(v, axis) * axis
                    n = -perp / (np.linalg.norm(perp) + 1e-6)
                    ctrl.append(c); disp.append(n * w * amt * fw)
        ctrl = np.array(ctrl, np.float32); disp = np.array(disp, np.float32)
        # signed inside/outside of face oval
        oval = poly_mask((S, S), P[FACE_OVAL])
        inside = cv2.GaussianBlur(oval, (0, 0), 1.0)
        sig_in, sig_out = 0.20 * fw, 0.09 * fw
        num = np.zeros((S, S, 2), np.float32); den = np.zeros((S, S), np.float32)
        dmin = np.full((S, S), 1e9, np.float32)
        for c, d in zip(ctrl, disp):
            d2 = (self.xx - c[0]) ** 2 + (self.yy - c[1]) ** 2
            k = 1.0 / (d2 + 4.0) ** 2                         # Shepard weights along contour
            num[..., 0] += k * d[0]; num[..., 1] += k * d[1]; den += k
            dmin = np.minimum(dmin, d2)
        F = num / den[..., None]
        sig = sig_out + (sig_in - sig_out) * inside
        F *= np.exp(-dmin / (2 * sig * sig))[..., None]
        self.debug['fmag_out'] = float(np.abs(F[..., 0])[oval < 0.01].max()) if (oval < 0.01).any() else 0
        return F

    # ---- teeth ----
    def teeth_pass(self, img, P, amt):
        """img: float32 BGR 0..1 (crop).  Returns modified image and teeth mask."""
        S = self.S
        mw = np.linalg.norm(P[78] - P[308]); op = np.linalg.norm(P[13] - P[14]) / (mw + 1e-6)
        # teeth effect weight follows mouth opening, EMA so it never pops
        tw = smoothstep(0.06, 0.16, op)
        self.teeth_w += (tw - self.teeth_w) * 0.35
        w = self.teeth_w * amt * self.presence
        if w < 1e-3:
            return img, None
        x0, y0 = np.floor(P[INNER_LIP].min(0)).astype(int) - 4
        x1, y1 = np.ceil(P[INNER_LIP].max(0)).astype(int) + 5
        x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, S), min(y1, S)
        U = 8                                           # work at 8x for clean masks
        roi = img[y0:y1, x0:x1]
        h, wd = roi.shape[:2]
        up = cv2.resize(roi, (wd * U, h * U), interpolation=cv2.INTER_CUBIC)
        up = np.clip(up, 0, 1)
        lip = poly_mask((h * U, wd * U), (P[INNER_LIP] - [x0, y0]) * U + (U - 1) / 2.0)
        lip = cv2.erode(lip, np.ones((5, 5), np.uint8))                 # stay off the lip line
        lip = cv2.GaussianBlur(lip, (0, 0), U * 0.5)
        lab = cv2.cvtColor(up, cv2.COLOR_BGR2Lab)                      # L 0..100, a,b ~ -127..127
        L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
        inl = lip > 0.5
        if inl.sum() < 20:
            return img, None
        # robust, temporally smoothed stats of the mouth interior
        Lp85 = np.percentile(L[inl], 85)
        Aref = np.median(A[inl & (L >= Lp85 - 3)])          # redness of the brightest (=teeth) pixels
        stats = np.array([Lp85, np.percentile(L[inl], 25), Aref])
        self.teeth_stats = stats if self.teeth_stats is None else self.teeth_stats * 0.8 + stats * 0.2
        hi, lo, aref = self.teeth_stats
        thr = lo + 0.30 * (hi - lo)
        bright = smoothstep(thr - 7, thr + 7, L)
        # include thin dark gaps *between* bright teeth: horizontal-only closing (<= ~2.5 px)
        gap_k = cv2.getStructuringElement(cv2.MORPH_RECT, (int(2.5 * U) | 1, 1))
        bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, gap_k)
        # ...but never tongue / gums / lips: anything clearly redder than the teeth themselves
        notred = 1 - smoothstep(aref + 7, aref + 14, A)
        tm = cv2.GaussianBlur(bright * notred, (0, 0), U * 0.4) * lip
        # (a) gap / ragged-edge softening: grey closing (fills dark gaps <~2 px with the
        #     neighbouring tooth colour) + bilateral to even out the rough enamel edges
        closed = cv2.morphologyEx(up, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3 * U + 1, 3)))
        bil = cv2.bilateralFilter(closed.astype(np.float32), 0, 0.10, U * 0.9)
        soft = up + (bil - up) * min(1.0, 0.25 + w)
        # (b) whiten: de-yellow and slight lift in LAB
        lab2 = cv2.cvtColor(np.clip(soft, 0, 1).astype(np.float32), cv2.COLOR_BGR2Lab)
        lab2[..., 2] = lab2[..., 2] - np.maximum(lab2[..., 2] - 2.0, 0) * 0.55 * w
        lab2[..., 1] = lab2[..., 1] - np.maximum(lab2[..., 1] - 1.0, 0) * 0.30 * w
        lab2[..., 0] = lab2[..., 0] + (100 - lab2[..., 0]) * 0.10 * w
        res = cv2.cvtColor(lab2, cv2.COLOR_Lab2BGR)
        out_up = up + (res - up) * tm[..., None]
        # (c) bite-line straightening (tiny vertical warp, upper incisal edge -> fitted curve)
        if self.bite > 0:
            out_up = self.bite_warp(out_up, tm, lip, U, w)
        out = cv2.resize(out_up, (wd, h), interpolation=cv2.INTER_AREA)
        tm_s = cv2.resize(tm, (wd, h), interpolation=cv2.INTER_AREA)
        lip_s = cv2.resize(lip, (wd, h), interpolation=cv2.INTER_AREA)
        img = img.copy()
        img[y0:y1, x0:x1] = roi + (out - roi) * lip_s[..., None]
        full = np.zeros((S, S), np.float32); full[y0:y1, x0:x1] = tm_s
        return img, full

    def bite_warp(self, up, tm, lip, U, w):
        H, W = tm.shape
        cols = np.arange(W)
        edge = np.full(W, np.nan)
        # for each column: lowest row of the *upper* bright run (teeth->dark/lower transition)
        for x in range(0, W):
            col = tm[:, x]
            idx = np.where(col > 0.5)[0]
            if len(idx) < U: continue
            # first contiguous run from the top = upper teeth
            br = np.where(np.diff(idx) > 2)[0]
            run_end = idx[br[0]] if len(br) else idx[-1]
            edge[x] = run_end
        ok = ~np.isnan(edge)
        if ok.sum() < W * 0.35:
            prof = np.zeros(W)
        else:
            co = np.polyfit(cols[ok], edge[ok], 2)
            fit = np.polyval(co, cols)
            prof = np.zeros(W); prof[ok] = fit[ok] - edge[ok]
            prof = np.clip(prof, -0.8 * U, 0.8 * U)                    # max ~0.8 native px
            prof = cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), U * 1.5).ravel()
        # temporal smoothing of the correction profile (resample if the ROI size changed)
        if self.bite_prof is None or len(self.bite_prof) != W:
            self.bite_prof = prof if self.bite_prof is None else np.interp(
                np.linspace(0, 1, W), np.linspace(0, 1, len(self.bite_prof)), self.bite_prof)
        self.bite_prof = self.bite_prof * 0.85 + prof * 0.15
        dy = (self.bite_prof * self.bite * w)[None, :] * tm         # only moves teeth pixels
        dy = cv2.GaussianBlur(dy.astype(np.float32), (0, 0), U * 0.6)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        return cv2.remap(up.astype(np.float32), xx, yy - dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    # ---- skin ----
    def skin_pass(self, img, P, amt):
        S = self.S
        m = poly_mask((S, S), P[FACE_OVAL])
        fw = np.linalg.norm(P[234] - P[454])
        hole = np.zeros((S, S), np.float32)
        for g in (L_EYE, R_EYE, L_BROW, R_BROW, OUTER_LIP):
            hole = np.maximum(hole, poly_mask((S, S), P[g]))
        hole = cv2.dilate(hole, np.ones((5, 5), np.uint8))
        m = np.clip(cv2.erode(m, np.ones((3, 3), np.uint8)) - hole, 0, 1)
        m = cv2.GaussianBlur(m, (0, 0), max(1.0, fw * 0.02))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        r = max(2, int(round(fw * 0.035)))
        base = np.dstack([guided_filter(gray, img[..., c], r, 0.0025) for c in range(3)])
        fine = img - cv2.GaussianBlur(img, (0, 0), 0.7)              # keep pore-level texture
        sm = base + fine
        return img + (sm - img) * (m * amt * self.presence)[..., None]

    def process(self, crop_bgr):
        S = self.S
        self.landmarks(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
        self.frame_i += 1
        if self.P is None or self.presence <= 1e-3:
            return crop_bgr
        P = self.P
        img = crop_bgr.astype(np.float32) / 255.0
        fw = np.linalg.norm(P[234] - P[454])
        yaw = (np.linalg.norm(P[1] - P[234]) - np.linalg.norm(P[1] - P[454])) / (fw + 1e-6)
        yaw_w = 1 - smoothstep(0.25, 0.5, abs(yaw))      # ease off on strongly turned heads
        if self.smooth > 0:
            img = self.skin_pass(img, P, self.smooth)
        if self.teeth > 0:
            img, _ = self.teeth_pass(img, P, self.teeth)
        if self.slim > 0:
            F = self.slim_field(P, self.slim * self.presence * yaw_w)
            img = cv2.remap(img, self.xx - F[..., 0], self.yy - F[..., 1], cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_REPLICATE)
        return np.clip(img * 255 + 0.5, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--start', type=float, default=0.0)
    ap.add_argument('--duration', type=float, default=None, help='seconds; default = to the end')
    ap.add_argument('--slim', type=float, default=0.03, help='contour pull-in as fraction of face width (0.03-0.06)')
    ap.add_argument('--teeth', type=float, default=0.5, help='teeth whitening/smoothing strength 0..1')
    ap.add_argument('--bite', type=float, default=0.5, help='bite-line straightening 0..1 (0 = off)')
    ap.add_argument('--smooth', type=float, default=0.25, help='skin smoothing 0..1')
    ap.add_argument('--roi', default='auto', help="'auto' or cx,cy,r of the round portrait window")
    ap.add_argument('--model', default=os.path.join(HERE, 'face_landmarker.task'))
    ap.add_argument('--crf', type=int, default=16)
    a = ap.parse_args()

    pr = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                         'stream=width,height,r_frame_rate', '-of', 'json', a.input], capture_output=True, text=True)
    st = json.loads(pr.stdout)['streams'][0]
    W, H = st['width'], st['height']; n, d = st['r_frame_rate'].split('/'); fps = float(n) / float(d)
    cx, cy, r = detect_circle(a.input) if a.roi == 'auto' else map(int, a.roi.split(','))
    r += 2                                               # include the anti-aliased rim in the crop
    x0, y0 = max(cx - r, 0), max(cy - r, 0); S = min(2 * r, W - x0, H - y0)
    print(f'video {W}x{H}@{fps:g}  roi center=({cx},{cy}) r={r-2}  crop {S}x{S} at ({x0},{y0})', file=sys.stderr)
    # paste-back mask: inside the circle, a hair smaller than the window (UI rim untouched)
    yy, xx = np.mgrid[0:S, 0:S]
    circ = ((xx + x0 - cx) ** 2 + (yy + y0 - cy) ** 2) <= (r - 5) ** 2

    tin = ['-ss', str(a.start)] + (['-t', str(a.duration)] if a.duration else [])
    dec = subprocess.Popen(['ffmpeg', '-v', 'error'] + tin + ['-i', a.input, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                            '-r', st['r_frame_rate'], '-i', '-'] + tin + ['-i', a.input,
                            '-map', '0:v', '-map', '1:a?', '-c:v', 'libx264', '-preset', 'medium', '-crf', str(a.crf),
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', a.output],
                           stdin=subprocess.PIPE)
    B = Beautifier(S, a.slim, a.teeth, a.smooth, a.bite, fps, a.model)
    nb = W * H * 3; i = 0; t0 = time.time(); tproc = 0.0
    while True:
        buf = dec.stdout.read(nb)
        if len(buf) < nb: break
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        crop = fr[y0:y0 + S, x0:x0 + S]
        tp = time.time()
        out = B.process(crop)
        tproc += time.time() - tp
        crop[circ] = out[circ]
        enc.stdin.write(fr.tobytes()); i += 1
        if i % 57 == 0:
            print(f'  {i} frames, {i / (time.time() - t0):.1f} fps overall, {i / tproc:.1f} fps beauty-only', file=sys.stderr)
    enc.stdin.close(); enc.wait(); dec.wait(); B.lm.close()
    el = time.time() - t0
    print(json.dumps({'frames': i, 'seconds': round(el, 2), 'fps_overall': round(i / el, 2),
                      'fps_beauty_only': round(i / tproc, 2), 'roi': [cx, cy, r - 2]}))


if __name__ == '__main__':
    main()
