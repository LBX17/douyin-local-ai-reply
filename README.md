# 抖音私信助手 · Douyin Local AI Reply

一个可自行部署的 Windows 桌面助手：扫码登录抖音，使用你配置的 AI 为一对一私信生成回复。默认只预览，手动开启后才实际发送；群聊始终跳过。

基于 [xyc667/douyin-auto-reply-assistant](https://github.com/xyc667/douyin-auto-reply-assistant) 改进，采用 MIT 许可证。

## 能做什么

- 桌面工作台：账号状态、AI 连接、私信监听、清晰的发送开关。
- 可配置的 OpenAI 兼容接口：Ollama、LM Studio、llama.cpp；另支持 Anthropic 格式接口。
- 模型列表读取、连接测试、独立试聊、个人风格样本收集。
- 多账号、本机知识库、会话上下文、手动回复后取消过时的待回复。
- 群聊及类型不明的消息不生成回复；发送结果不明确时不自动重试。

**当前支持抖音网页私信，不包含微信自动回复。** 本项目不附带模型权重、不自动下载大模型，也不会把每位使用者的聊天记录混在一起训练。风格样本保存不等于完成微调；如使用已微调模型，在模型服务中加载适配器后接入即可。

## 安装（Windows 10 / 11）

1. 安装 [Python 3.11 或 3.12](https://www.python.org/downloads/)，安装时勾选 **Add Python to PATH**。
2. 安装 [Node.js LTS](https://nodejs.org/)。
3. 下载仓库 ZIP 并解压到固定目录，或 `git clone`。
4. 双击 **setup.bat**。它会创建项目专用 Python 环境，安装依赖和 Chromium。首次安装需要联网。
5. 双击 **start.bat** 打开助手。可选运行 `create-shortcut.ps1` 创建桌面入口。

```powershell
git clone https://github.com/LBX17/douyin-local-ai-reply.git
cd douyin-local-ai-reply
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Python 界面主要在 Windows 验证；尚未验证 macOS / Linux。无需安装 canvas 等原生 Node 构建依赖。

## 连接自己的 AI

先在模型工具中下载并启动适合你的电脑的聊天模型，再打开助手的 **AI 设置**。项目不会限定必须使用 27B 模型。

| 模型服务 | 接口类型 | API 根地址 |
| --- | --- | --- |
| Ollama | `ollama` | `http://127.0.0.1:11434/v1` |
| LM Studio 本地服务 | `lm_studio` | `http://127.0.0.1:1234/v1` |
| llama.cpp server | `llama_cpp` | `http://127.0.0.1:8080/v1` |
| 其他 OpenAI 兼容服务 | `openai` | 服务商提供的 HTTPS 根地址，通常以 `/v1` 结尾 |
| Anthropic 格式服务 | `anthropic` | 服务商提供的根地址 |

点击 **读取模型列表**，选择服务实际返回的模型名称，点击 **保存配置 → 测试 AI 连接**。本机无认证服务的 API Key 可留空；需要认证的服务请填写自己的密钥。远程地址要求 HTTPS。

Ollama 接口说明：[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)。LM Studio 接口说明：[OpenAI compatibility](https://lmstudio.ai/docs/developer/openai-compat)。llama.cpp 说明：[server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)。

“开启模型思考”只向 `llama_cpp` 发送扩展参数；其他兼容接口使用标准聊天参数。部分推理模型会将思考计入生成上限，若正文不完整，请提高上限或调整服务端设置。模型必须返回完整正文，带原始 `<think>` 内容或超长/截断的回复会被跳过。

## 开始回复

1. 点击 **扫码登录**，在打开的抖音网页中自行扫码、手机确认。登录等待最长 5 分钟。
2. 先用 **试聊与风格** 检查模型表达和回复逻辑。试聊不会发送抖音消息。
3. 点击 **开启监听**，新私信的拟回复显示在消息动态中。
4. 需要真实回复时勾选 **实际发送回复** 并确认。只处理之后收到的新私信，旧预览不会补发。
5. 点击 **停止** 或退出应用结束监听。每次启动都会回到预览模式。同一安装目录不能重复运行。

快捷键：`Ctrl+1` 工作台，`Ctrl+2` AI 设置。知识库按完整消息匹配，避免短词误命中。

## 风格、知识库和隐私

- 在试聊窗口把参考答案修改为自己会说的话，再保存样本。文件为 `datas/style_samples.jsonl`；收集不会自动训练。
- 点 **知识库** 编辑固定问答，或参考 `examples/knowledge_base.example.json`。知识库为空时使用 AI。
- `.env`、`accounts.json` 保存登录凭证；`config_ai.env` 保存 AI 密钥；`datas/` 保存浏览器登录、会话、样本及日志。**这些文件只属于你的电脑，不应提交或分享。**
- 会话上下文只在本机按账号分开保存，读取时保留最近 24 小时的上下文；日志和样本不会自动清理，需要用户自行管理。没有产品遥测或集中训练服务。
- 使用云端 AI 会把收到的私信及相关上下文发到你配置的服务；本机模型请求发到本机地址。不要公开自己的配置、模型适配器或私人聊天数据。
- 不会可靠知道主人的实时位置、饮食和日程；默认规则避免编造这些事实。AI 表达仍可能出错，建议先保持预览。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 没有读取到模型 | 先启动模型服务并加载模型，检查端口；确认填写的是 API 根地址 |
| 登录超时 | 在 5 分钟内完成网页登录和手机确认；重新扫码；检查网络 |
| 收到消息但没发出 | 查看是否处于预览、已开始监听、一对一文字私信，以及 AI 是否返回完整回复 |
| 回复显示未确认送达 | 查看抖音网页确认实际情况；助手不会自动重发，避免重复发送 |
| 双击启动没有窗口 | 查看 `datas/startup.err.log`；先运行 setup.bat 安装依赖 |

本项目依赖非官方网页接口，页面、认证或风控变化可能导致失效。请遵守平台规则，并保持人工检查；不支持批量营销或群聊自动发送。

## 开发与发布检查

```powershell
python -X utf8 -m unittest discover -s tests -v
git add .
python check_repo_secrets.py --staged
```

离线测试使用合成消息和 mock，不会向真实账号发消息。GitHub Actions 会检查群聊过滤、发送结果、会话逻辑、AI 接口及发布文件。扫描器仅检查 Git 导出，检测到凭证或私有运行目录时返回失败；它不能替代人工审查。

发布只包含源码、空配置示例和合成测试。来源说明见 [NOTICE.md](NOTICE.md)，许可证见 [LICENSE](LICENSE)。
