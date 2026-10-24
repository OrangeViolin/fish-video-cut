# fish-video-cut

01fish 口播与录屏的成片流水线。

从原片到可发布版本，按同一套标准做完：精剪、片头与 BGM、敏感信息打码、大字字幕、封面、质检、发布。它是一份 [Cursor](https://cursor.com) Agent Skill，也可以单独运行 `scripts/` 里的工具。

## 适合谁

- 做 01fish 口播、录屏，或带画中画人脸小窗的人
- 用 Cursor Agent 按固定步骤出片的人
- 要在视频号和小红书按品牌口径发布的人

## 你得到什么

- 完整步骤说明：[`SKILL.md`](./SKILL.md)
- 打码：逐帧跟踪后台数据气泡，高斯模糊加 16px 马赛克，再抽帧复核
- 字幕：风格 B「干净科技」（另备风格 A），墨绿底条、逐字高亮、关键词色块、贴纸
- 混音示例：约 5 秒品牌片头、0.25 秒交叉淡化、人声处 BGM ducking、响度约 −14 LUFS
- 字幕字体，以及视频号 / 小红书的发布检查清单

## 仓库结构

```
SKILL.md                 # Cursor skill：完整流水线
requirements.txt
LICENSE                  # MIT
scripts/
  mosaic/                # 后台数据跟踪打码 + 抽帧复核
    track_bubble.py
    apply_mosaic.py
    check.py
  subs/                  # 字幕烧录（风格 A 活泼综艺 / B 干净科技）
    subs.py
    stickers.json
    fonts/               # Noto Sans CJK SC Black、得意黑 SmileySans
  mix/                   # 片头 / BGM / 音效混音示例
    build_mix.py
```

## 快速上手

在仓库根目录执行。脚本路径相对仓库，克隆到任意目录即可。

环境：

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/)（含 `ffprobe`）
- 转写建议另装 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `large-v3`（`requirements.txt` 里已注释）
- 片头可选另仓的 video-shotcraft（Remotion）。本仓库不附带音源

```bash
git clone https://github.com/OrangeViolin/fish-video-cut.git
cd fish-video-cut
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

mkdir -p video-01/{out,final}
# 原片放到 video-01/raw.mp4
```

`.gitignore` 已忽略 `video-*/`、`*.mp4`、`out/`、`final/`。换一条视频：

```bash
export FISH_VIDEO=video-02   # 默认 video-01
```

常用命令：

```bash
# 跟踪后台数据气泡，再打码
python scripts/mosaic/track_bubble.py \
  --video video-01/out/cut.mp4 \
  --out video-01/out/track.json

python scripts/mosaic/apply_mosaic.py \
  --video video-01/out/cut.mp4 \
  --track video-01/out/track.json \
  --audio-from video-01/out/cut.mp4 \
  --out-nosub video-01/out/mosaic.mp4

# 字幕（风格 B）。5 秒片头、0.25 秒交叉淡化时 --offset 为 4.75；没有片头用 0
python scripts/subs/subs.py burn --style B \
  --input video-01/out/mosaic.mp4 \
  --output video-01/final/final.mp4 \
  --offset 4.75
```

`scripts/subs/subs.py` 按这个顺序找文案和转写：

| 文件 | 优先 | 回退 |
| --- | --- | --- |
| 逐句文案 | `$FISH_VIDEO/cues.txt` | `scripts/subs/cues.txt` |
| 贴纸 | `$FISH_VIDEO/stickers.json` | `scripts/subs/stickers.json` |
| 转写 | `$FISH_VIDEO/out/transcript.json` | `scripts/out/transcript.json` |
| 剪辑点 | `$FISH_VIDEO/out/edl.md` | `scripts/out/edl.md` |

打码复核用 `scripts/mosaic/check.py`（片源根目录看 `FISH_VIDEO`）。混音示例 `scripts/mix/build_mix.py` 写了一条成片的时间点，换片时改其中的剪辑点和音效。音源目录用 `SHOTCRAFT_AUDIO`（默认 `assets/audio`）：

```bash
export SHOTCRAFT_AUDIO=/path/to/video-shotcraft/assets/audio
python scripts/mix/build_mix.py both
```

字体在 `scripts/subs/fonts/`（Noto Sans CJK SC Black、得意黑 / SmileySans）。其余步骤、质检和发布确认见 [`SKILL.md`](./SKILL.md)。

## 品牌

| 项 | 值 |
| --- | --- |
| 墨绿 | `#1A3328` |
| 鱼红 | `#C44536` |
| 宣纸 | `#F2EDE3` |
| 默认 BGM | Mixkit「House Vibez」(Lily J)，正片人声处 ducking，响度约 −14 LUFS，true peak 不超过 −1 dBTP |
| 封面 | 3:4 `1080×1440`，另备 16:9 `1920×1080`；人脸用真实视频帧 |
| 字体 | 字幕用 Noto Sans CJK SC Black；封面用得意黑（Smiley Sans） |

## 发布检查清单

- 视频号：3:4 封面，勾选「声明原创」；位置勿误填
- 小红书：打开原创声明；内容类型声明只能选一项，选「笔记含AI合成内容」
- 发布前由本人确认。先看预览，确认后再点发表，只点一次，然后到作品列表核对状态

## 示例成片

示例成片将随后加入，此处先留位。

## 赞赏

赞赏码将随后加入，此处先留位。

## 在 Cursor 里用

仓库根目录的 `SKILL.md` 就是 skill。克隆后链到 Cursor 的 skills 目录：

```bash
mkdir -p ~/.cursor/skills
ln -s "$(pwd)" ~/.cursor/skills/fish-video-cut
```

Agent 会按 `SKILL.md` 开头的 `description`，在剪辑口播或录屏成片时加载这条流水线。

## 许可与素材

- 代码以根目录 [MIT License](./LICENSE) 发布。
- Mixkit 等第三方 BGM / 音效请遵守各自授权；本仓库不附带音源文件。
- `scripts/subs/fonts/` 里的 Noto Sans CJK 与得意黑（Smiley Sans）按各自字体许可随仓库分发，使用前请再核对当前文件的许可。
