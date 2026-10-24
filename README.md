# fish-video-cut

01fish 口播 / 录屏成片流水线：精剪 → 片头+BGM → 轻度美颜 → 敏感信息打码 → 大字字幕 → 封面 → 质检 → 发布。

这是一份可以克隆使用的 [Cursor](https://cursor.com) Agent Skill，也可以单独运行 `scripts/` 里的 Python 工具。美颜只做确定性的局部处理（瘦脸、牙齿、磨皮），人脸定位用 MediaPipe Face Landmarker。

## 仓库结构

```
SKILL.md                 # Cursor skill：完整流水线说明
requirements.txt         # Python 依赖
LICENSE                  # MIT
scripts/
  beauty/                # 轻度美颜（MediaPipe）
    beauty.py
    compare.py           # 原片 / 轻度 / 中度对比图
    face_landmarker.task
  mosaic/                # 后台数据跟踪打码 + 抽帧复核
    track_bubble.py
    apply_mosaic.py
    check.py
  subs/                  # 字幕烧录（风格 A 活泼综艺 / B 干净科技）
    subs.py
    stickers.json
    fonts/               # Noto Sans CJK SC Black、得意黑 SmileySans
  mix/                   # 片头 / BGM / 音效混音示例（含一条成片的时间点）
    build_mix.py
    build_mix_beauty_light.py
```

## 快速上手

在仓库根目录执行下面的命令。脚本路径都相对仓库，克隆到任意目录即可。

### 1. 环境

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/)（含 `ffprobe`）
- 美颜需要 OpenGL/EGL（Debian/Ubuntu：`sudo apt install libegl1`）
- 转写建议另装 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `large-v3`（`requirements.txt` 里已注释，按需打开）
- 片头可选另仓的 video-shotcraft（Remotion）。`scripts/mix` 是对接示例，本仓库不附带音源

```bash
git clone https://github.com/OrangeViolin/fish-video-cut.git
cd fish-video-cut
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

字体在 `scripts/subs/fonts/`（Noto Sans CJK SC Black、得意黑 / SmileySans）。美颜模型是 `scripts/beauty/face_landmarker.task`。

### 2. 每条视频建工作目录

素材不要提交。`.gitignore` 已忽略 `video-*/`、`*.mp4`、`out/`、`final/`。

```bash
mkdir -p video-01/{out,final}
# 把成片原料放到 video-01/raw.mp4
```

换一条视频时：

```bash
export FISH_VIDEO=video-02   # 默认 video-01
```

### 3. 按流水线跑（摘要）

完整步骤、质检和发布确认都在 [`SKILL.md`](./SKILL.md)。常用命令：

```bash
# 美颜（默认轻度参数）
python scripts/beauty/beauty.py \
  --input video-01/out/cut.mp4 \
  --output video-01/out/beauty.mp4 \
  --slim 0.03 --teeth 0.45 --bite 0.4 --smooth 0.2 --roi auto

# 字幕烧录（风格 B「干净科技」）
python scripts/subs/subs.py burn --style B \
  --input video-01/out/beauty-mosaic.mp4 \
  --output video-01/final/final.mp4 \
  --offset 4.75
```

`--offset 4.75` 对应约 5 秒片头、0.25 秒交叉淡化。正片上直接烧字幕时用 `--offset 0`。

`scripts/subs/subs.py` 按这个顺序找文案和转写（先看当前视频目录，没有再用脚本旁的示例文件）：

| 文件 | 优先 | 回退 |
| --- | --- | --- |
| 逐句文案 | `$FISH_VIDEO/cues.txt` | `scripts/subs/cues.txt` |
| 贴纸 | `$FISH_VIDEO/stickers.json` | `scripts/subs/stickers.json` |
| 转写 | `$FISH_VIDEO/out/transcript.json` | `scripts/out/transcript.json` |
| 剪辑点 | `$FISH_VIDEO/out/edl.md` | `scripts/out/edl.md` |

打码：`scripts/mosaic/track_bubble.py` 跟踪气泡，`apply_mosaic.py` 烧高斯模糊加 16px 马赛克，`check.py` 抽帧对比。`check.py` 的「处理后」路径相对当前工作目录；片源根目录同样看 `FISH_VIDEO`。

混音：`scripts/mix/build_mix.py` 与 `build_mix_beauty_light.py` 是一条 01fish 成片的示例（EDL、音效时间点写在脚本里）。换片时改这些时间点。音源目录用 `SHOTCRAFT_AUDIO`（默认 `assets/audio`）。

```bash
export SHOTCRAFT_AUDIO=/path/to/video-shotcraft/assets/audio
python scripts/mix/build_mix.py both
```

### 4. 品牌约定（01fish）

| 项 | 值 |
| --- | --- |
| 墨绿 | `#1A3328` |
| 鱼红 | `#C44536` |
| 宣纸 | `#F2EDE3` |
| 默认 BGM | Mixkit「House Vibez」(Lily J)，正片人声处 ducking，响度约 −14 LUFS，true peak 不超过 −1 dBTP |
| 封面 | 3:4 `1080×1440`，另备 16:9 `1920×1080`；人脸用真实视频帧 |

### 5. 发布检查清单

- 视频号：3:4 封面，勾「声明原创」；位置勿误填
- 小红书：打开原创声明；内容类型声明只能选一项，选「笔记含AI合成内容」
- 发布前必须本人确认。先发预览，确认后再点发表，只点一次，然后到作品列表核对状态

## Cursor Skill

仓库根目录的 `SKILL.md` 就是 skill。克隆后链到 Cursor 的 skills 目录：

```bash
mkdir -p ~/.cursor/skills
ln -s "$(pwd)" ~/.cursor/skills/fish-video-cut
```

Agent 会按 `SKILL.md` 开头的 `description`，在剪辑口播或录屏成片时加载这条流水线。

## 许可与素材

- 代码以根目录 [MIT License](./LICENSE) 发布。
- Mixkit 等第三方 BGM / 音效请遵守各自授权；本仓库不附带音源文件。
- `scripts/beauty/face_landmarker.task` 是 MediaPipe 模型，随美颜脚本一起提供。
- `scripts/subs/fonts/` 里的 Noto Sans CJK 与得意黑（Smiley Sans）按各自字体许可随仓库分发，使用前请再核对当前文件的许可。

## 维护

面向 01fish 实战剪辑沉淀。Issue / PR 欢迎。只想复用美颜或字幕时，拷对应子目录即可：美颜带上 `face_landmarker.task`，字幕带上 `fonts/`。
