#!/usr/bin/env python3
"""01fish shotcraft 合成：BGM 床 + 正片 SFX + 片头/正片拼接 + 响度归一。
用法: build_mix.py [sub|nosub|both]"""
import json, subprocess, sys, os, re
# Episode example. FISH_VIDEO is the per-video folder (default video-01).
# SHOTCRAFT_AUDIO is the video-shotcraft assets/audio directory (bgm/ + sfx/).
ROOT = os.environ.get('FISH_VIDEO', 'video-01')
SC = os.path.join(ROOT, 'shotcraft'); W = os.path.join(SC, 'work', 'mix')
LIB = os.environ.get('SHOTCRAFT_AUDIO', os.path.join('assets', 'audio'))
OUT = os.path.join(ROOT, 'out')
INTRO=f'{SC}/remotion/out/intro-sfx.mp4'
FPS=30
INTRO_DUR=150/FPS          # 5.0s
XF=0.25                    # 交叉淡化时长
MAIN_AT=INTRO_DUR-XF       # 正片在成片中的起点 4.75s
# BGM 网格（与 remotion/src/timeline.ts 同值）
BEAT=0.489; B0=0.07; BGM_START=B0+16*BEAT-84/FPS
SRC=f'{LIB}/bgm/house-vibez.mp3'
def run(cmd):
    print('+',' '.join(cmd) if isinstance(cmd,list) else cmd, file=sys.stderr)
    return subprocess.run(cmd,check=True,capture_output=True,text=True)
def dur(p): return float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',p]).stdout)

# 正片关键演示节点 SFX（时间 = 正片 final.mp4 时间轴，秒；来源：transcript.json 词时间 + edl.md 段映射 + 抽帧确认）
# raw→final: final = seg.final_start + (raw - seg.raw_start)
EDL={6:(26.456,22.87),10:(42.279,36.03),17:(75.771,62.37),18:(80.613,64.82)}
def f(seg,raw): rs,fs=EDL[seg]; return fs+(raw-rs)
PEAK={'switch-tap':0.002,'paper-crumple-quick':0.263,'typewriter-return-bell':0.666,'sparkle-touch':0.474}  # 48kHz 实测峰值滞后(s)
MAIN_SFX=[
 # (目标峰值时间(final), 文件, 增益dB, 截断秒, 说明)
 (f(6,27.90),'ui/switch-tap','-13',0.6,'扫码登录成功：口播「连接上了」+ 画面回到聊天、后台已登录 → 真实开关拟音（接通）'),
 (f(10,43.30),'paper/paper-crumple-quick','-12',1.2,'40 篇草稿删完：口播「全部都删掉了」，画面空草稿箱 → 纸团揉皱拟音'),
 (f(17,77.32),'text/typewriter-return-bell','-15',1.6,'成稿：口播「markdown 的文档」，画面 .md 成稿卡 → 打字机回车铃'),
 (f(18,83.40),'light/sparkle-touch','-14',1.8,'头图：口播「出了头图」，画面头图卡 → 单发 sparkle（light/）'),
]
def build(variant):
    main=f'{OUT}/final.mp4' if variant=='sub' else f'{OUT}/final-nosub.mp4'
    out=f'{SC}/final-shotcraft.mp4' if variant=='sub' else f'{SC}/final-shotcraft-nosub.mp4'
    md=dur(main); total=MAIN_AT+md
    # 1) BGM 床：src[BGM_START:X] + src[X-64拍:X]（重复 64 拍，拍线拼接）+ src[X:]，拼点 20ms 交叉
    X=B0+96*BEAT; R=X-64*BEAT
    bed=f'{W}/bed.wav'
    run(['ffmpeg','-v','error','-y','-i',SRC,'-filter_complex',
      f'[0:a]aresample=48000,asplit=3[a][b][c];'
      f'[a]atrim={BGM_START:.4f}:{X:.4f},asetpts=N/SR/TB[s1];'
      f'[b]atrim={R:.4f}:{X:.4f},asetpts=N/SR/TB[s2];'
      f'[c]atrim={X:.4f},asetpts=N/SR/TB[s3];'
      f'[s1][s2]acrossfade=d=0.02:c1=tri:c2=tri[s12];[s12][s3]acrossfade=d=0.02:c1=tri:c2=tri[o]',
      '-map','[o]','-c:a','pcm_s16le',bed])
    # 2) 正片 SFX 轨（相对正片时间 + 片头偏移；按峰值滞后前移）
    inputs=[]; parts=[]
    for i,(t,src,g,cut,_) in enumerate(MAIN_SFX):
        name=src.split('/')[-1]; start=MAIN_AT+t-PEAK[name]
        inputs+=['-i',f'{LIB}/sfx/{src}.mp3']
        ms=int(round(start*1000))
        parts.append(f'[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{cut},afade=t=out:st={cut-0.25}:d=0.25,volume={g}dB,adelay={ms}|{ms},apad=whole_dur={total:.3f}[x{i}]')
    n=len(MAIN_SFX)
    run(['ffmpeg','-v','error','-y',*inputs,'-filter_complex',';'.join(parts)+';'+''.join(f'[x{i}]' for i in range(n))+f'amix=inputs={n}:normalize=0,atrim=0:{total:.3f}[o]','-map','[o]','-c:a','pcm_s24le',f'{W}/sfx-main.wav'])
    # 3) 音频混合：人声(正片音轨) + 片头 SFX + 正片 SFX + BGM（音量包络 + sidechain ducking）
    vms=int(round(MAIN_AT*1000))
    INTRO_GAIN=-6.5   # 片头：BGM 明显在前
    SPEECH_GAIN=-14.5 # 人声段静态压低
    fc=(
      f'[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay={vms}|{vms},apad=whole_dur={total:.3f},atrim=0:{total:.3f},asplit=2[voice][key];'
      f'[0:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={total:.3f},atrim=0:{total:.3f}[isfx];'
      f'[2:a]aformat=channel_layouts=stereo,atrim=0:{total:.3f}[msfx];'
      # BGM 包络：0–0.2s 淡入；片头段 INTRO_GAIN；4.6→5.4s 下沉到 SPEECH_GAIN；末 3s 淡出
      f'[3:a]aformat=channel_layouts=stereo,atrim=0:{total:.3f},'
      f"volume='pow(10,(if(lt(t,4.6),{INTRO_GAIN},if(lt(t,5.4),{INTRO_GAIN}+({SPEECH_GAIN}-({INTRO_GAIN}))*(t-4.6)/0.8,{SPEECH_GAIN})))/20)':eval=frame,"
      f'afade=t=in:st=0:d=0.2,afade=t=out:st={total-3.0:.3f}:d=3.0[bgm0];'
      f'[bgm0][key]sidechaincompress=threshold=0.08:ratio=2.2:attack=60:release=500:makeup=1:knee=4[bgm];'
      f'[bgm]asplit=2[bgmmix][bgmstem];'
      f'[voice][isfx][msfx][bgmmix]amix=inputs=4:normalize=0[pre]'
    )
    pre=f'{W}/pre-{variant}.wav'; stem=f'{W}/bgm-stem-{variant}.wav'
    run(['ffmpeg','-v','error','-y','-i',INTRO,'-i',main,'-i',f'{W}/sfx-main.wav','-i',bed,'-filter_complex',fc,
         '-map','[pre]','-c:a','pcm_s24le',pre,'-map','[bgmstem]','-c:a','pcm_s24le',stem])
    # 4) 两遍 loudnorm（linear）→ -14 LUFS / TP ≤ -1
    m=run(['ffmpeg','-hide_banner','-nostats','-i',pre,'-af','loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json','-f','null','-'])
    js=json.loads(re.search(r'\{[^{}]*"input_i"[^{}]*\}',m.stderr,re.S).group(0))
    af=(f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={js['input_i']}:measured_TP={js['input_tp']}:measured_LRA={js['input_lra']}:"
        f"measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true,aresample=48000")
    # 5) 画面：片头 + 正片 xfade（30fps），编码 H.264 + AAC
    vf=(f'[0:v]fps=30,format=yuv420p,setsar=1[v0];[1:v]fps=30,format=yuv420p,setsar=1[v1];'
        f'[v0][v1]xfade=transition=fade:duration={XF}:offset={MAIN_AT}[v]')
    run(['ffmpeg','-v','error','-y','-i',INTRO,'-i',main,'-i',pre,'-filter_complex',vf+f';[2:a]{af}[a]',
         '-map','[v]','-map','[a]','-c:v','libx264','-preset','slow','-crf','18','-profile:v','high','-pix_fmt','yuv420p','-r','30',
         '-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',out])
    json.dump({'variant':variant,'main':main,'main_dur':md,'total':total,'loudnorm_pass1':js,'af':af,
               'main_sfx':[(round(MAIN_AT+t,3),s,g,c,d) for t,s,g,c,d in MAIN_SFX],'bgm_start_s':BGM_START,
               'bed_splice':{'X':X,'R':R},'gains':{'intro':INTRO_GAIN,'speech':SPEECH_GAIN}},
              open(f'{W}/mix-{variant}.json','w'),ensure_ascii=False,indent=1)
    print(out)
if __name__=='__main__':
    v=sys.argv[1] if len(sys.argv)>1 else 'both'
    for x in (['sub','nosub'] if v=='both' else [v]): build(x)
