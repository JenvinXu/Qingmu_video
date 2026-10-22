# 贡献指南

感谢参与青幕 Lime Studio。

## 开始之前

1. 先搜索现有 Issue，确认问题或需求尚未被记录。
2. 较大的功能请先开 Issue 说明使用场景、交互流程和模型依赖。
3. 不要提交 API Key、用户项目数据库、生成媒体、运行日志或版权状态不清楚的素材。

## 开发流程

```powershell
npm ci
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements-lock.txt
npm run dev
```

提交前运行：

```powershell
npm run build
npm run test:agent
npm run test:backend
```

## 代码约定

- TypeScript、React 和 CSS 使用仓库中的 Prettier 配置。
- Python 遵循 Ruff 规则，并保持 FastAPI 路由、领域服务、模型适配器和工作流的边界。
- 前端与 Agent 工具应调用同一后端领域能力，避免复制业务逻辑。
- 新增模型时需声明能力边界，包括时长、比例、分辨率和参考素材上限；不要静默丢弃用户输入。
- 新增生成流程时需保存真实任务状态，并支持失败信息、取消与可安全重试。
- 用户可编辑内容默认自动保存，界面只保留能推动当前流程的操作。

## Pull Request

PR 请说明具体问题、行为变化和验证方式。界面改动请附截图或短视频；模型相关改动请使用脱敏日志，并说明哪些验证使用了真实服务、哪些使用了测试替身。

提交代码即表示你有权按本仓库许可证提供这些内容。改编第三方代码、提示词或 Skills 时，请同时补充来源、许可证和必要署名。
