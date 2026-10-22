# 第三方组件与来源

- Codex：OpenAI，Apache-2.0，https://github.com/openai/codex 。版本和提交见 upstream.json。发行包使用官方 npm 二进制与资源。
- Electron：MIT，https://github.com/electron/electron 。React：MIT，https://github.com/facebook/react 。Lucide：ISC。
- FastAPI：MIT。Python：PSF。SQLite：Public Domain。Pillow：HPND。HTTPX：BSD-3-Clause。Edge TTS：LGPL-3.0，使用公开在线语音服务，需要联网。
- FFmpeg / ffprobe：本机 Gyan FFmpeg 9.0.1 full shared build，GPL 组件；构建与源代码入口 https://www.gyan.dev/ffmpeg/builds/ ，https://ffmpeg.org/download.html 。本地验收发行包保留配套动态库；进一步对外分发需一并履行对应源代码和许可证要求。
- 映序 / Video Studio 工作流参考：MIT，Copyright (c) 2026 罗小罗通行。青幕独立实现业务与前端，参考了文案→分镜→素材→旁白→字幕→合成的工作流。
- Screenwriting Skills：Terry Jia，MIT，https://github.com/jtydhr88/screenwriting-skills 。青幕内置 `screenwriting` Skill 提炼其前提→结构→人物→场景→对白工作流，并针对一分钟短剧与本地工具契约重新编写；没有复制其受第三方版权约束的书籍引文。
- Visual Skills：Serge Shima，CC BY 4.0，https://github.com/smixs/visual-skills 。青幕内置 `visual-video` Skill 是经过翻译、压缩并针对 Agnes 与结构化分镜重新编写的改编版本。原作者链接：https://t.me/aimastersme 、https://sergeshima.com 、https://aimasters.me 。
- 素材来源保存在资产元数据中。Openverse 检索结果保留作者署名和独立许可，按对应来源页面要求使用。AI 生成资产标记为 AI 生成。
