#!/usr/bin/env python3
"""01fish 口播字幕 v2：生成 ASS（A 活泼综艺 / B 干净科技）并烧到任意无字幕底片上。

用法
  python3 subs.py ass    --style A --offset 4.75 -o out.ass          # 只生成 ASS
  python3 subs.py burn   --style A --input base.mp4 --output out.mp4 --offset 4.75 [--ss 36.5 --to 45.5]
  python3 subs.py sample --style A --input base.mp4 --output sample-A.mp4 --offset 4.75 --seg 36.4-45.6 --seg 53.4-62.4
  python3 subs.py timing                                             # 打印每条字幕的对齐时间（检查用）

--offset = 字幕时间（正片时间轴）在底片上的偏移秒数。final-shotcraft 系列底片 = 片头 5.0 - 交叉淡化 0.25 = 4.75；
           直接烧正片（不含片头）用 0。--ss/--seg 的时间都是底片时间。
"""
import argparse, json, os, re, subprocess, sys, difflib, tempfile
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PARENT = os.path.dirname(HERE)
# Per-video workdir. Override when the folder is not ./video-01.
VIDEO = os.environ.get('FISH_VIDEO', 'video-01')
FONTS = os.path.join(HERE, 'fonts')


def resolve(*candidates):
    """First existing file, otherwise the preferred (documented) path."""
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return candidates[0]


def cues_path():
    return resolve(os.path.join(VIDEO, 'cues.txt'), os.path.join(HERE, 'cues.txt'))


def stickers_path():
    return resolve(os.path.join(VIDEO, 'stickers.json'), os.path.join(HERE, 'stickers.json'))


def transcript_path():
    return resolve(
        os.path.join(VIDEO, 'out', 'transcript.json'),
        os.path.join(SCRIPT_PARENT, 'out', 'transcript.json'),
    )


def edl_path():
    return resolve(
        os.path.join(VIDEO, 'out', 'edl.md'),
        os.path.join(SCRIPT_PARENT, 'out', 'edl.md'),
    )
W, H = 994, 1080

# ---------- brand colours (ASS = &HAABBGGRR) ----------
def c(hexrgb, a=0):
    r, g, b = hexrgb[1:3], hexrgb[3:5], hexrgb[5:7]
    return f'&H{a:02X}{b}{g}{r}&'.upper().replace('&H', '&H', 1)
def cc(hexrgb):  # inline colour tag value (no alpha)
    return f'&H{hexrgb[5:7]}{hexrgb[3:5]}{hexrgb[1:3]}&'.upper()
INK, RED, PAPER, YEL, WHITE = '#1A3328', '#C44536', '#F2EDE3', '#FFD84D', '#FFFFFF'

# ---------- layout ----------
CX, BY = 362, 946      # 主字幕中心 x、底边 y（输入框 y≈960 之上）
MAXW = 660             # 主字幕最大宽度：x 32–692，人像小窗左缘 ≥ 722

# ---------- timing ----------
def load_edl():
    segs = []
    for l in open(edl_path(), encoding='utf-8'):
        m = re.match(r'\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|', l)
        if m: segs.append(tuple(map(float, m.groups()[1:4])))
    return segs

def norm_chars(s):
    return [ch.lower() for ch in s if re.match(r'[0-9A-Za-z\u4e00-\u9fff]', ch)]

def whisper_chars():
    edl = load_edl(); d = json.load(open(transcript_path(), encoding='utf-8'))
    out = []
    for s in d['segments']:
        for w in s['words']:
            chs = norm_chars(w['word'])
            if not chs: continue
            mid = (w['start'] + w['end']) / 2
            for a, b, c0 in edl:
                if a - 0.05 <= mid <= b + 0.05:
                    t0 = c0 + max(w['start'], a) - a; t1 = c0 + min(w['end'], b) - a
                    step = max(t1 - t0, 0.02) / len(chs)
                    for i, ch in enumerate(chs): out.append((ch, t0 + i * step, t0 + (i + 1) * step))
                    break
    return out

def parse_cues(path):
    cues = []
    for l in open(path, encoding='utf-8'):
        l = l.rstrip('\n')
        if not l.strip() or l.startswith('#'): continue
        force = None
        m = re.search(r'\s*@([\d.]+)\s*$', l)
        if m: force = float(m.group(1)); l = l[:m.start()]
        runs = []  # (text, kind) kind: n / k / g(Grok Bot)
        for part in re.split(r'(\[[^\]]+\])', l):
            if not part: continue
            kind = 'k' if part.startswith('[') else 'n'
            txt = part.strip('[]') if kind == 'k' else part
            for i, p2 in enumerate(re.split(r'(Grok Bot)', txt)):
                if p2: runs.append((p2, 'g' if p2 == 'Grok Bot' else kind))
        cues.append({'runs': runs, 'force': force, 'text': ''.join(r[0] for r in runs)})
    return cues

def align(cues):
    wc = whisper_chars(); wt = [x[0] for x in wc]
    ours = []  # (cue index, run index, char index in run text)
    for ci, cu in enumerate(cues):
        for ri, (txt, k) in enumerate(cu['runs']):
            for chi, ch in enumerate(txt):
                if norm_chars(ch): ours.append((ci, ri, chi, ch.lower()))
    sm = difflib.SequenceMatcher(None, [o[3] for o in ours], wt, autojunk=False)
    t = [None] * len(ours)
    for a, b, n in sm.get_matching_blocks():
        for i in range(n): t[a + i] = (wc[b + i][1], wc[b + i][2])
    # interpolate gaps
    known = [i for i, x in enumerate(t) if x]
    for i in range(len(t)):
        if t[i]: continue
        prv = max([k for k in known if k < i], default=None); nxt = min([k for k in known if k > i], default=None)
        if prv is None: t[i] = (t[nxt][0] - 0.15 * (nxt - i), t[nxt][0] - 0.15 * (nxt - i - 1)); continue
        if nxt is None: t[i] = (t[prv][1] + 0.15 * (i - prv - 1), t[prv][1] + 0.15 * (i - prv)); continue
        a0, b0 = t[prv][1], t[nxt][0]; span = (b0 - a0) / (nxt - prv)
        t[i] = (a0 + span * (i - prv - 1) + 0.0, a0 + span * (i - prv))
    for cu in cues: cu['chars'] = []
    for (ci, ri, chi, ch), tt in zip(ours, t): cues[ci]['chars'].append((ri, chi, tt[0], tt[1]))
    for i, cu in enumerate(cues):
        cu['s'] = cu['force'] if cu['force'] is not None else cu['chars'][0][2]
        cu['e_speech'] = cu['chars'][-1][3]
    for i, cu in enumerate(cues):
        nxt = cues[i + 1]['s'] if i + 1 < len(cues) else cu['e_speech'] + 1.0
        e = cu['e_speech'] + 0.35
        if nxt - e < 0.45: e = nxt  # 连续说话：无缝衔接
        cu['e'] = min(max(e, cu['s'] + 0.6), nxt)
    return cues

# ---------- width estimate ----------
_adv = {}
def adv_table(font):
    if font not in _adv:
        p = {'A': os.path.join(FONTS, 'SmileySans-Oblique.ttf'), 'B': os.path.join(FONTS, 'NotoSansCJKsc-Black.otf')}[font]
        f = TTFont(p); o = f['OS/2']; cmap = f.getBestCmap(); hm = f['hmtx']
        _adv[font] = (cmap, hm, o.usWinAscent + o.usWinDescent)
    return _adv[font]
def text_w(font, s, size):
    cmap, hm, asc = adv_table(font)
    return sum(hm[cmap.get(ord(ch), cmap.get(0x20))][0] for ch in s) * size / asc

def ts(t):
    t = max(t, 0); cs = int(round(t * 100)); return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'

# ---------- styles ----------
HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 994
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def style_line(name, font, size, prim, sec, outc, back, bs, outline, shadow, spacing=0, align=2):
    return f'Style: {name},{font},{size},{prim},{sec},{outc},{back},0,0,0,0,100,100,{spacing},0,{bs},{outline},{shadow},{align},0,0,0,1'

def ms(x): return int(round(x * 1000))

# ===== A：活泼综艺 =====
A_SIZE, A_KW = 98, 1.16
def build_A(cues, stickers, off):
    st = [style_line('A_Back', 'Smiley Sans Oblique', A_SIZE, c(WHITE), c(WHITE), c(INK), c(INK, 0x10), 1, 11, 5, 2),
          style_line('A_Main', 'Smiley Sans Oblique', A_SIZE, c(WHITE), c(WHITE), c(INK), c(INK, 0xFF), 1, 4, 0, 2),
          style_line('A_StBack', 'Smiley Sans Oblique', 170, c(YEL), c(YEL), c(INK), c(INK), 1, 14, 7, 2),
          style_line('A_StMain', 'Smiley Sans Oblique', 170, c(YEL), c(YEL), c(INK), c(INK, 0xFF), 1, 5, 0, 2),
          style_line('A_StTag', 'Smiley Sans Oblique', 74, c(WHITE), c(WHITE), c(RED), c(INK, 0x60), 3, 12, 4, 2)]
    ev = []
    for cu in cues:
        s, e = cu['s'] - 0.06 + off, cu['e'] + off
        if e <= 0: continue
        w = sum(text_w('A', t, A_SIZE) * (A_KW if k != 'n' else 1) for t, k in cu['runs'])
        f = min(1.0, MAXW / w)
        rot = -2 if (cues.index(cu) % 2 == 0) else 2
        def sc(k_scale):  # 入场：0.5 → 1.12 → 0.97 → 1.0（带回弹），返回该 run 的缩放动画
            b = 100 * f * k_scale
            return (f'\\fscx{b*0.5:.0f}\\fscy{b*0.5:.0f}\\t(0,110,\\fscx{b*1.12:.0f}\\fscy{b*1.12:.0f})'
                    f'\\t(110,170,\\fscx{b*0.97:.0f}\\fscy{b*0.97:.0f})\\t(170,220,\\fscx{b:.0f}\\fscy{b:.0f})')
        for layer, sty in ((0, 'A_Back'), (1, 'A_Main')):
            txt = f'{{\\an2\\pos({CX},{BY})\\fad(40,90)\\frz{rot}\\t(0,180,\\frz0)}}'
            for ri, (t, k) in enumerate(cu['runs']):
                tags = sc(1.0)
                if k != 'n':
                    p = ms(next(ch[2] for ch in cu['chars'] if ch[0] == ri) - (cu['s'] - 0.06))
                    p = max(p, 160)
                    b = 100 * f
                    fill = cc(RED) if k == 'g' else cc(YEL)
                    rim = cc(WHITE) if k == 'g' else cc(INK)
                    # 说到该词时：变色 + pop 1.0 → 1.38 → 1.16
                    tags = (sc(1.0) + f'\\t({p},{p+1},\\1c{fill}' + (f'\\3c{rim}' if layer == 1 else '') + ')'
                            + f'\\t({p},{p+90},\\fscx{b*1.38:.0f}\\fscy{b*1.38:.0f})\\t({p+90},{p+200},\\fscx{b*A_KW:.0f}\\fscy{b*A_KW:.0f})')
                    if k == 'g':  # Grok Bot 从一开始就是鱼红
                        tags = sc(A_KW) + f'\\1c{fill}' + (f'\\3c{rim}' if layer == 1 else '')
                else:
                    tags += f'\\1c{cc(WHITE)}' + (f'\\3c{cc(INK)}' if layer == 1 else '')
                txt += f'{{{tags}}}{t}'
            ev.append(f'Dialogue: {layer},{ts(s)},{ts(e)},{sty},,0,0,0,,{txt}')
    for k in stickers:
        s, e = k['t'] - 0.10 + off, k['t'] + k['dur'] + off
        if e <= 0: continue
        x, y = k['x'], k['y']
        pop = '\\fscx0\\fscy0\\t(0,130,\\fscx128\\fscy128)\\t(130,210,\\fscx92\\fscy92)\\t(210,270,\\fscx100\\fscy100)'
        out = f'\\t({ms(k["dur"])-60},{ms(k["dur"])+100},\\fscx130\\fscy130\\alpha&HFF&)'
        bw = text_w('A', k['big'], 170)
        bsize = '' if bw < 520 else f'\\fs{170*520/bw:.0f}'
        for layer, sty in ((10, 'A_StBack'), (11, 'A_StMain')):
            ev.append(f'Dialogue: {layer},{ts(s)},{ts(e)},{sty},,0,0,0,,{{\\an2\\pos({x},{y+40})\\frz-7{bsize}{pop}{out}}}{k["big"]}')
        ev.append(f'Dialogue: 12,{ts(s+0.12)},{ts(e)},A_StTag,,0,0,0,,{{\\an8\\pos({x+20},{y+62})\\frz-7\\fscx0\\fscy0\\t(0,120,\\fscx115\\fscy115)\\t(120,200,\\fscx100\\fscy100){out}}}{k["small"]}')
    return HEADER.replace('{styles}', '\n'.join(st)) + '\n'.join(ev) + '\n'

def rrect(w, h, r):
    w, h = int(w), int(h)
    return (f'm {r} 0 l {w-r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h-r} b {w} {h} {w} {h} {w-r} {h} '
            f'l {r} {h} b 0 {h} 0 {h} 0 {h-r} l 0 {r} b 0 0 0 0 {r} 0')

# ===== B：干净科技 =====
B_SIZE = 92
def build_B(cues, stickers, off):
    st = [style_line('B_Bar', 'Noto Sans CJK SC Black', B_SIZE, c(INK, 0x3A), c(INK, 0x3A), c(INK, 0xFF), c(INK, 0xFF), 1, 0, 0),
          style_line('B_Chip', 'Noto Sans CJK SC Black', B_SIZE, c(YEL, 0xFF), c(YEL, 0xFF), c(YEL), c(INK, 0xFF), 3, 5, 0),
          style_line('B_Text', 'Noto Sans CJK SC Black', B_SIZE, c(WHITE), c('#9FB3A8'), c(INK, 0xFF), c(INK, 0xFF), 1, 0, 0),
          style_line('B_StBox', 'Noto Sans CJK SC Black', 140, c(YEL), c(YEL), c(INK, 0x08), c(INK, 0xFF), 3, 18, 0),
          style_line('B_StTag', 'Noto Sans CJK SC Black', 62, c(WHITE), c(WHITE), c(RED), c(INK, 0xFF), 3, 12, 0)]
    ev = []
    for cu in cues:
        s0 = cu['s'] - 0.08
        s, e = s0 + off, cu['e'] + off
        if e <= 0: continue
        w = sum(text_w('B', t, B_SIZE) for t, k in cu['runs']) + 16
        f = min(1.0, MAXW / w)
        b = 100 * f
        ent = (f'\\fscx{b*0.9:.0f}\\fscy{b*0.9:.0f}\\t(0,120,\\fscx{b*1.04:.0f}\\fscy{b*1.04:.0f})\\t(120,190,\\fscx{b:.0f}\\fscy{b:.0f})')
        head = f'{{\\an2\\move({CX},{BY+22},{CX},{BY},0,170)\\fad(110,90)}}'
        # 每个字的 \kf 时长（厘秒），从 s0 开始
        kchars = {(ri, chi): (a, b2) for ri, chi, a, b2 in cu['chars']}
        # 底条：圆角矩形，宽度按落定后的文字宽度估算（关键词 1.06x）
        tw = sum(text_w('B', t, B_SIZE) * (1.06 if k != 'n' else 1) for t, k in cu['runs']) * f
        bw_, bh_ = tw + 44, B_SIZE * f * 0.98 + 22
        ev.append(f'Dialogue: 0,{ts(s)},{ts(e)},B_Bar,,0,0,0,,{{\\an2\\move({CX},{BY+22+12},{CX},{BY+12},0,170)\\fad(110,90)'
                  f'\\fscx90\\fscy90\\t(0,120,\\fscx104\\fscy104)\\t(120,190,\\fscx100\\fscy100)\\p1}}{rrect(bw_, bh_, 14)}')
        for layer, sty in ((1, 'B_Chip'), (2, 'B_Text')):
            txt = head
            cur = s0
            for ri, (t, k) in enumerate(cu['runs']):
                p = None
                if k != 'n':
                    p = ms(next(ch[2] for ch in cu['chars'] if ch[0] == ri) - s0); p = max(p, 150)
                tags = ent
                if layer == 1:
                    chip = cc(RED) if k == 'g' else cc(YEL)
                    tags += '\\3a&HFF&' if k == 'n' else (f'\\3c{chip}\\3a&HFF&\\t({p},{p+1},\\3a&H00&)'
                                                          if k == 'k' else f'\\3c{chip}\\3a&H00&')
                if layer == 2:
                    if k == 'k': tags += f'\\1c{cc(WHITE)}\\2c{cc(WHITE)}\\t({p},{p+1},\\1c{cc(INK)}\\2c{cc(INK)})'
                    elif k == 'g': tags += f'\\1c{cc(WHITE)}\\2c{cc(WHITE)}'
                    else: tags += f'\\1c{cc(WHITE)}'
                if k != 'n' and layer >= 1 and p is not None:
                    tags += (f'\\t({p},{p+90},\\fscx{b*1.18:.0f}\\fscy{b*1.18:.0f})\\t({p+90},{p+200},\\fscx{b*1.06:.0f}\\fscy{b*1.06:.0f})')
                    if k == 'g': tags = tags.replace(f'\\t({p},{p+90}', f'\\t({0},{1}', 0)
                elif k != 'n' and layer == 0 and p is not None:
                    tags += (f'\\t({p},{p+90},\\fscx{b*1.18:.0f}\\fscy{b*1.18:.0f})\\t({p+90},{p+200},\\fscx{b*1.06:.0f}\\fscy{b*1.06:.0f})')
                # 逐字 karaoke
                seg = ''
                for chi, ch in enumerate(t):
                    if (ri, chi) in kchars:
                        a, b2 = kchars[(ri, chi)]
                        d = max(int(round((b2 - cur) * 100)), 1); cur += d / 100
                        seg += f'{{\\kf{d}}}{ch}'
                    else:
                        seg += ch
                txt += f'{{{tags}}}{seg}'
            ev.append(f'Dialogue: {layer},{ts(s)},{ts(e)},{sty},,0,0,0,,{txt}')
    for k in stickers:
        s, e = k['t'] - 0.10 + off, k['t'] + k['dur'] + off
        if e <= 0: continue
        x, y = k['x'], k['y']
        d = ms(k['dur'])
        bw = text_w('B', k['big'], 140)
        bsize = '' if bw < 460 else f'\\fs{140*460/bw:.0f}'
        ev.append(f'Dialogue: 10,{ts(s)},{ts(e)},B_StBox,,0,0,0,,{{\\an2\\move({x+60},{y+40},{x},{y+40},0,200)\\fad(140,160)'
                  f'\\fscx80\\fscy80\\t(0,140,\\fscx104\\fscy104)\\t(140,220,\\fscx100\\fscy100){bsize}}}{k["big"]}')
        ev.append(f'Dialogue: 11,{ts(s+0.15)},{ts(e)},B_StTag,,0,0,0,,{{\\an8\\move({x+60},{y+66},{x},{y+66},0,180)\\fad(120,160)}}{k["small"]}')
    return HEADER.replace('{styles}', '\n'.join(st)) + '\n'.join(ev) + '\n'

def make_ass(style, off):
    cues = align(parse_cues(cues_path()))
    stickers = json.load(open(stickers_path(), encoding='utf-8'))['stickers']
    return {'A': build_A, 'B': build_B}[style](cues, stickers, off)

def burn(style, inp, outp, off, ss=None, to=None, crf=18):
    eff = off - (ss or 0)
    work = os.path.join(HERE, 'work')
    os.makedirs(work, exist_ok=True)
    fd, ass = tempfile.mkstemp(suffix='.ass', dir=work); os.close(fd)
    open(ass, 'w', encoding='utf-8').write(make_ass(style, eff))
    cmd = ['ffmpeg', '-v', 'error', '-y']
    if ss is not None: cmd += ['-ss', f'{ss}']
    if to is not None: cmd += ['-t', f'{to - (ss or 0)}']
    cmd += ['-i', inp, '-vf', f"subtitles={ass}:fontsdir={FONTS}", '-c:v', 'libx264', '-preset', 'medium', '-crf', str(crf),
            '-pix_fmt', 'yuv420p', '-c:a', 'copy' if ss is None else 'aac', *(['-b:a', '192k'] if ss is not None else []), '-movflags', '+faststart', outp]
    subprocess.run(cmd, check=True)
    os.remove(ass)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['ass', 'burn', 'sample', 'timing'])
    ap.add_argument('--style', choices=['A', 'B'], default='A')
    ap.add_argument('--offset', type=float, default=4.75)
    ap.add_argument('--input'); ap.add_argument('--output', '-o')
    ap.add_argument('--ss', type=float); ap.add_argument('--to', type=float)
    ap.add_argument('--seg', action='append', help='底片时间段 a-b，可多次')
    ap.add_argument('--crf', type=int, default=18)
    a = ap.parse_args()
    if a.cmd == 'timing':
        for cu in align(parse_cues(cues_path())):
            print(f"{cu['s']:7.2f} {cu['e']:7.2f}  {cu['text']}")
    elif a.cmd == 'ass':
        open(a.output, 'w', encoding='utf-8').write(make_ass(a.style, a.offset))
    elif a.cmd == 'burn':
        burn(a.style, a.input, a.output, a.offset, a.ss, a.to, a.crf)
    elif a.cmd == 'sample':
        parts = []
        for i, sg in enumerate(a.seg):
            x, y = map(float, sg.split('-'))
            p = os.path.join(HERE, 'work', f'_seg{a.style}{i}.mp4'); burn(a.style, a.input, p, a.offset, x, y, a.crf); parts.append((p, y - x))
        inputs = sum([['-i', p] for p, _ in parts], [])
        fl = ''.join(f'[{i}:v]fade=t=in:st=0:d=0.12,fade=t=out:st={d-0.12:.3f}:d=0.12[v{i}];[{i}:a]afade=t=in:d=0.12,afade=t=out:st={d-0.12:.3f}:d=0.12[a{i}];'
                     for i, (_, d) in enumerate(parts))
        fl += ''.join(f'[v{i}][a{i}]' for i in range(len(parts))) + f'concat=n={len(parts)}:v=1:a=1[v][a]'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', fl, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264',
                        '-crf', str(a.crf), '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', a.output], check=True)
        for p, _ in parts: os.remove(p)

if __name__ == '__main__':
    main()
