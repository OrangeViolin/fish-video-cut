<div align="center">

# fish-video-cut

**[中文](README.md)** | English

[![GitHub stars](https://img.shields.io/github/stars/OrangeViolin/fish-video-cut)](https://github.com/OrangeViolin/fish-video-cut/stargazers)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Cursor](https://img.shields.io/badge/Cursor-skill-C44536)](SKILL.md)

**01fish talking-head and screen-recording cut pipeline.**

Hand a recording to a Cursor Agent and get a publish-ready cut: trim, intro and BGM, mosaic, subtitles, covers, QC, publish.

This is an Agent Skill. The scripts in this repo also run on their own.

It is a deterministic edit pipeline. The picture comes from your own footage.

</div>

Chinese documentation is the source of truth: **[README.md](README.md)**.

## Pipeline

1. Trim
2. Intro / BGM (optional [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) opener)
3. Mosaic sensitive on-screen data
4. Subtitles (style B)
5. Covers (3:4 and 16:9)
6. QC stills
7. Publish after you confirm

## Samples

12-second previews. Click a cover.

<div align="center">

<a href="assets/demos/ep01-rea-preview.mp4"><img src="assets/demos/ep01-rea-cover.jpg" width="270" alt="AI news EP.01 REA cover"></a>
&nbsp;&nbsp;
<a href="assets/demos/ep-bot-tutorial-preview.mp4"><img src="assets/demos/ep-bot-tutorial-cover.jpg" width="270" alt="One-person company bot tutorial cover"></a>

</div>

## Install

```text
Install this skill: https://github.com/OrangeViolin/fish-video-cut
```

```bash
git clone https://github.com/OrangeViolin/fish-video-cut.git
cd fish-video-cut
mkdir -p ~/.cursor/skills
ln -s "$(pwd)" ~/.cursor/skills/fish-video-cut
```

Full usage, brand colors (`#1A3328`, `#C44536`, `#F2EDE3`), the publish checklist, and the tip QR are in [README.md](README.md).

## License

[MIT](LICENSE). Mixkit music is not bundled. Demo covers and previews are 01fish samples.
