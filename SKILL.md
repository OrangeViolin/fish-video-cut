---
name: fish-video-cut
description: >-
  Use when editing a 01fish talking-head or screen-recording video (with a
  picture-in-picture face cam) into a publish-ready cut: trim, light beauty
  retouch, mosaic sensitive data, intro/BGM/SFX, big animated subtitles, and
  covers.
---
# fish-video-cut：01fish 视频成片流水线

脚本都放在 `scripts/`（beauty、mosaic、subs、mix）。每条视频新建一个工作目录 `./video-XX/`，原片放到 `raw.mp4`。命令在仓库根目录执行。换工作目录时设置环境变量 `FISH_VIDEO`（默认 `video-01`）。

## 0. 准备
- 用 `ffprobe` 看分辨率、帧率和时长，再在一帧上找到画中画人脸圆窗的位置（cx,cy,r）。
- 用 faster-whisper large-v3 转写，输出 `$FISH_VIDEO/out/transcript.json` 和 `$FISH_VIDEO/out/transcript.srt`。

## 1. 精剪
- 用 silencedetect 加转写，去掉口误、重复、长停顿和废话，剪辑点记到 `$FISH_VIDEO/out/edl.md`。
- 出 `$FISH_VIDEO/out/final-nosub.mp4`。
- 有判断的删减要单独告诉用户。

## 2. 片头、BGM、音效（video-shotcraft）
- 用另仓的 video-shotcraft（Remotion）做一个约 5s 的品牌片头，和正片做 0.25s 交叉淡化。
- BGM 用 Mixkit 免费授权曲，正片人声处做 sidechain ducking。关键节点加 Mixkit 音效。
- 参考 `scripts/mix/build_mix.py`。音源目录用 `SHOTCRAFT_AUDIO`（默认 `assets/audio`，本仓库不附带 Mixkit 文件）。
- 响度 loudnorm 到 -14 LUFS，true peak 不超过 -1。

## 3. 轻度美颜（只用确定性处理，不做 AI 换脸）
- 运行：`python scripts/beauty/beauty.py --input <in> --output <out> --slim 0.03 --teeth 0.45 --bite 0.4 --smooth 0.2 --roi auto`
- 默认就用这组轻度参数。中度（0.05/0.8/0.8/0.4）用户觉得太明显。
- 先出样片，用 `scripts/beauty/compare.py` 拼前后对比图，用户确认后再跑全片。
- 依赖 MediaPipe 和 libegl1，模型文件是 `scripts/beauty/face_landmarker.task`。

## 4. 敏感信息打码
- 后台数据（粉丝数、阅读数、收入等）出现的时段要逐帧跟踪打码：高斯模糊加 16px 马赛克。参考 `scripts/mosaic/track_bubble.py`、`apply_mosaic.py`。
- 用 OCR 抽帧（`check.py`）验证已经不可读。

## 5. 字幕（风格 B「干净科技」）
- `scripts/subs/subs.py`：先把逐句文案整理成 `$FISH_VIDEO/cues.txt`，贴纸标注写进 `$FISH_VIDEO/stickers.json`（没有贴纸文件时用仓库里的 `scripts/subs/stickers.json`）。
- 样式：Noto Sans CJK SC Black 大号白字，墨绿半透明底条，卡拉 OK 逐字高亮，关键词彩色色块（Grok Bot 用鱼红），关键时刻加贴纸标注。
- 字幕和贴纸都避开人脸圆窗。
- 烧录命令：`python scripts/subs/subs.py burn --style B --input <美颜+打码 nosub 底片> --output $FISH_VIDEO/final/final.mp4 --offset <片头时长-交叉淡化>`（5s 片头时是 4.75）。
- 先用 `sample` 出片段给用户看，再烧全片。

## 6. 封面
- 按 content-pipeline 的 `references/cover-quality.md` 做 3:4（1080×1440）和 16:9（1920×1080）两张。
- 品牌色：墨绿 #1A3328、鱼红 #C44536、宣纸 #F2EDE3。字体：得意黑。
- 人脸用视频里的真实帧，AI 只能生成无人、无字的背景。

## 7. 质检与交付
- 在片头、打码段和字幕密集段各抽帧检查，记到 `$FISH_VIDEO/final/qc-*.jpg`。
- 交付 `$FISH_VIDEO/final/final.mp4`、`$FISH_VIDEO/out/final-nosub.mp4` 和封面。

## 8. 发布（每一步都要等用户确认）
- 视频号助手（channels.weixin.qq.com）：扫码登录，用 3:4 封面，勾「声明原创」。
- 小红书创作平台（creator.xiaohongshu.com）：网页端就行，不用云手机。打开原创声明；内容类型声明只能选一项，选「笔记含AI合成内容」。
- 先给用户发预览，用户说发再点 发表/发布，只点一次，然后去作品列表确认状态。
