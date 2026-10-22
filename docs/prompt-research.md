# 提示词设计依据

青幕的默认提示词采用明确的分区、固定输出格式和少量示例，使文本模型可以稳定地把想法转成可直接制作的镜头，同时允许用户在提示词库中继续调整。

## 参考资料

- [SeaArt Storyboard Prompt Assistant](https://github.com/seaartpublic/skills/blob/main/storyboard-prompt-assistant/SKILL.md)：每镜只表达一个连续、可见的动作，默认使用短镜头和整数时长；镜头要写清主体、动作、环境、光线、景别、运镜、声音和连续性。
- [Google Cloud Veo 视频生成提示词指南](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/video-gen-prompt-guide?hl=zh-CN)：显式描述动作、场景语境、镜头运动、机位和镜头语言。
- [Google Cloud Veo 3.1 Prompting Guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1)：按摄影语言、主体、动作、环境、风格与氛围组织视频提示词，并使用参考素材和首尾帧维持连续性。
- [Anthropic Prompting Best Practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)：提供充分上下文、明确约束、结构化分区和符合目标格式的示例。
- [script2video](https://github.com/reaink/script2video)：图片模型和视频模型分工，按模型时长能力生成片段，并可利用上一镜尾帧保持串行镜头连续性。

## 落地规则

1. 想法生成文案时，每行必须使用 `（起始秒-结束秒）分镜N：本镜文案`，例如 `（0-5秒）分镜1：女孩推开雨夜车站的大门。`。
2. 分镜编号从 1 连续递增；时间从 0 开始且相邻镜头无空档、无重叠；每镜时长为整数。
3. 一个镜头只承载一个连续动作。文案同时交代景别或机位、主体、动作、环境、光线、声音以及与前后镜头有关的连续性信息。
4. 一键分镜按时间段和分镜号逐行解析。结构化分镜的“本分镜文案”逐字复制冒号后的内容，时长直接取结束秒减起始秒，不允许模型改写或总结。
5. 项目分镜数量始终来自已解析的分镜行，界面不再提供独立的数量输入。
6. 图片提示词只描述可见的静态首帧；视频提示词描述从该首帧继续发生的动作、运镜、节奏和声音。角色与物品只能引用本项目资产配置中的 ID。
7. 用户修改提示词库后，后端在下一次 Agent 任务中直接使用保存版本。默认模板升级只替换未被用户修改过的旧默认文本。
