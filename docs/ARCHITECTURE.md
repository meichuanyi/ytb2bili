# ytb2bili 架构文档

> 本文档基于当前代码库（`main.go` / `internal/` / `pkg/` / `web/`）整理，用于说明系统分层、核心执行模型、模块职责与数据流向。

---

## 1. 项目定位

ytb2bili 是一套**视频翻译与分发流水线系统**，对外提供两类核心能力：

1. **本地视频翻译与审片**：下载/上传视频 → 抽取音轨 → ASR 转写 → 字幕翻译 → AI 生成标题/简介/标签 → 字幕配音（TTS） → 音画同步播放与字幕编辑。
2. **YouTube / 抖音 → Bilibili 一键搬运**：在上述处理链基础上追加 B 站投稿、字幕上传，并支持账号绑定、定时扫描、自动投稿。

系统形态为**单体二进制**：Go 后端 + 内嵌的 Next.js 前端静态产物，单端口对外服务。

---

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       浏览器 (Next.js SPA)                                 │
│  dashboard / tasks / videos / accounts / settings / assistant ...          │
└───────────────▲──────────────────────────────────┬───────────────────────┘
                │ HTTP JSON (/api/v1/**, /agent/v1/**)                      
                │                                  │ 静态资源 (embed.FS)
┌───────────────┴──────────────────────────────────▼───────────────────────┐
│                    Go 服务 (Gin + uber-go/fx)                              │
│                                                                            │
│  middleware        handler           service          workflow             │
│  ├ cors            ├ video            ├ video_service  ├ Chain (任务链)     │
│  ├ local_jwt       ├ video_process    ├ youtube_...    ├ Step (步骤)        │
│  ├ api_key_auth    ├ youtube          ├ binding_...    ├ Pipeline(队列)     │
│  ├ any_auth        ├ tts / subtitle   ├ user_settings  ├ ProgressTracker    │
│  └ analytics       ├ upload_to_bili   └ agent_open     └ 3 条业务链          │
│                    └ agent / agent_open                                    │
│                                                                            │
│  background (CronJob)   analytics    updater    server(静态托管)            │
├──────────────────────────────────────────────────────────────────────────┤
│                        pkg/ 可复用能力层                                    │
│  tools(工具集)  llm(多厂商)  bilibili(投稿/字幕)  tikhub(抖音)  store(GORM)  │
│  agent(Eino NanoAgent)  utils(ffmpeg/crypto/file)                           │
└───────────────▲──────────────────────────────────────────────────────────┘
                │ 外部依赖
  yt-dlp / ffmpeg │ OpenAI/Deepseek/Qwen/Ollama │ Azure/Tencent/Edge/OpenAI TTS
  Bcut ASR        │ Bilibili API                │ TikHub / YouTube OAuth / 飞书
  MySQL / PostgreSQL
```

---

## 3. 技术栈

### 后端

| 领域 | 选型 | 位置 |
| --- | --- | --- |
| 语言 / 运行时 | Go（见 `go.mod`） | 全仓库 |
| DI 容器 | `go.uber.org/fx`（模块化 + Lifecycle 优雅退出） | `internal/bootstrap/app.go` |
| Web 框架 | Gin | `internal/handler/router.go`、`internal/server/server.go` |
| 日志 | `go.uber.org/zap` | 全局注入 |
| ORM / DB | GORM + MySQL / PostgreSQL（启动时 AutoMigrate） | `pkg/store` |
| 配置 | TOML（`config.toml`） | `internal/config` |
| Agent 框架 | CloudWeGo Eino | `pkg/agent`、`pkg/tools/registry.go` |
| LLM 接入 | 自研统一客户端（OpenAI 兼容协议） | `pkg/llm` |
| 下载 / 转码 | 外部进程 `yt-dlp`、`ffmpeg` | `pkg/tools`、`pkg/utils` |
| ASR | Bcut（必剪）ASR、Whisper | `pkg/tools/asr_*.go`、`bcut_transcriber.go` |
| TTS | Azure / Tencent / Edge / OpenAI | `pkg/tools/tts_*.go` |
| B 站 | 自研投稿 + 字幕上传 SDK | `pkg/bilibili` |
| 抖音解析 | TikHub API + 直连解析 | `pkg/tikhub` |
| 文档 | Swagger（swag 生成，`docs/` 目录） | `internal/handler/swagger_handler.go` |

### 前端

| 领域 | 选型 |
| --- | --- |
| 框架 | Next.js 14（App Router）+ React 18 + TypeScript |
| 样式 | Tailwind CSS + `clsx` / `tailwind-merge` |
| 请求 | Axios（`web/src/lib/api-client.ts` 统一封装） |
| 播放 | `react-player` + 自研音画同步播放器（`web/src/lib/video-player/`） |
| 图标 / 反馈 | `lucide-react`、`react-icons`、`react-hot-toast` |
| 其他 | `page-agent`（页面智能体）、`qrcode.react`、`firebase` |

---

## 4. 后端分层

### 4.1 启动与装配（bootstrap）

`main.go` 只做三件事：注入构建信息 → `bootstrap.NewApp()` → `app.Start()` / 阻塞等待 `app.Done()` / `app.Stop()`。

`internal/bootstrap/app.go` 用 fx 声明全部模块装配顺序：

```go
fx.Provide(zap.NewDevelopment, config.LoadAppConfig, config.AgenticConfig, newUpdater, ...)
ToolsModule            // 提供 group:"tools,flatten"（Agent 工具集）
agent.Module           // 消费 tools，产出 *agent.NanoAgent
analytics.Module
store.Module           // *gorm.DB（含自动迁移）
service.Module         // 业务服务（用户设置、绑定、YouTube OAuth、License…）
background.Module      // CronJob 后台任务
workflow.YouTubeWorkflowModule / DouyinWorkflowModule / BilibiliWorkflowModule
fx.Provide(workflow.NewProcessingService)   // 跨链编排
handler.Module         // 注册路由
server.Module          // 启动 HTTP Server
```

关键约定：**注册顺序即生命周期顺序**，`handler.Module` 必须先于 `server.Module`。

### 4.2 目录职责速查

| 路径 | 职责 |
| --- | --- |
| `main.go` | 入口，注入 Version/BuildTime/CommitSHA |
| `internal/bootstrap` | fx 应用装配（`app.go`）、Agent 工具注册（`tools_wiring.go`） |
| `internal/config` | `AppConfig` TOML 结构、Provider 解析、TTS 配置 |
| `internal/handler` | 全部 HTTP Handler + 集中式路由注册（`router.go`） |
| `internal/middleware` | CORS、本地 JWT、AppID/AppSecret 鉴权、APIKey 鉴权、Cookie 解密 |
| `internal/service` | 业务服务层：视频、用户/系统设置、账号绑定、YouTube OAuth 客户端工厂、Agent OpenAPI |
| `internal/workflow` | **核心**：Step / Chain / Pipeline / ProgressTracker / 三条业务链 |
| `internal/background` | `CronJob`：B 站自动投稿扫描、字幕补传、YouTube Feed 同步 |
| `internal/analytics` | 埋点客户端 + Gin 中间件 |
| `internal/updater` | 自更新（含 yt-dlp 更新） |
| `internal/server` | Gin Server、前端静态托管（`//go:embed all:out`） |
| `pkg/store` | GORM 连接、迁移、模型定义（`model/`） |
| `pkg/tools` | 原子工具：下载/抽音/转写/翻译/TTS/转码/水印/DB 查询/订阅 |
| `pkg/llm` | 多厂商 LLM 统一客户端（Eino ChatClient） |
| `pkg/bilibili` | 登录凭据、投稿、分区、字幕上传、加解密 |
| `pkg/tikhub` | 抖音分享解析 |
| `pkg/agent` | Eino NanoAgent（对话式驱动工具调用） |
| `pkg/utils` | ffmpeg 封装、加解密、文件、YouTube 工具函数 |

---

## 5. 核心执行模型：Step / Chain / Pipeline

这是整个系统的心脏，位于 `internal/workflow`。

### 5.1 Step（步骤）

```go
type Step interface {
    Name() string
    Execute(ctx context.Context, input any) (any, error)
    IsRequired() bool   // 失败是否中断整条链
    Order() int         // 执行顺序，越小越先
}
```

可选增强接口：

- `StepWithSkip.ShouldSkip(ctx, input) bool` —— 运行前判断是否跳过（如未开启 TTS）。
- `StepWithHooks.OnSuccess / OnError` —— 生命周期钩子。
- `StepSkippedError` —— 步骤运行中抛出「可容忍错误」，链将其记为 `skipped` 并继续。
- `BaseStep` / `NewBaseStepWithOrder(name, required, order)` 提供默认实现；`ToolStep` 进一步把「构造参数 → 执行工具 → 回填结果」三段式模板化（`tool_step.go`）。
- 步骤通过 fx 的 `group:"steps"` 收集，`AsStep()` 用 `fx.Annotate` 完成接口转换与分组标注，**新增步骤只需在 workflow 模块的 `StepProvidersForGroup(...)` 中追加一行构造函数**。

### 5.2 Chain（任务链）

`Chain` 收集 `group:"steps"`，按 `Order()` 排序后串行执行，上一步输出作为下一步输入（数据载体为 `*VideoContext`）。

执行语义（`chain.go`）：

| 情况 | 行为 |
| --- | --- |
| 每步开始前 | 检查 `ctx.Done()`，已取消则立即返回 |
| `ShouldSkip` 为真 / 命中 `RestartFromStep` 之前的步骤 | 记 `skipped`，`continue` |
| 执行成功 | 记 `completed`，调用 `OnSuccess` |
| 返回 `StepSkippedError` | 记 `skipped`，调用 `OnError`，继续 |
| 失败且 `IsRequired()` | 记 `failed`，**中断整条链** |
| 失败且非必需 | 记 `failed`，继续下一步 |

- `WithTracker(tracker)` / `clone()`：为单次运行附加进度追踪器且不污染原实例。
- `RestartFromStep`：`VideoContext` 上指定续跑起点，起点之前的步骤在运行时严格跳过。

### 5.3 ProgressTracker（进度持久化）

`progress_tracker.go` 将每个步骤的 `pending / running / completed / failed / skipped` 状态写入 `tb_task_steps` 表，前端据此渲染任务队列。同时把 `videoID`、`userID`、tracker 本身注入 `context`，供步骤内部上报中间进度。

### 5.4 Pipeline（多阶段队列，可选）

`pipeline.go` 提供 producer-consumer 式多阶段流水线（`prepare → download → transcribe → translate → metadata → tts → finalize`），每阶段可配 worker 数、`Submit` 返回事件 channel。

> 现状说明：`ProcessingService` 中的三条业务链走的是 **Chain 串行模型**；`Pipeline` 目前以空 handler 占位（`NewProcessingService` 中传入 no-op），`SubmitToPipeline` 则退化为 `ChainPipeline`（把整条 Chain 作为一个任务提交）。因此 Pipeline 属于**已预留、尚未完全落地**的并发模型。

### 5.5 三条业务链

| 链 | 文件 | 步骤组成 |
| --- | --- | --- |
| `YouTubeChain` | `youtube_workflow.go` | Initialize(1) → DownloadVideo(2) → DownloadThumbnail(3) → ExtractAudio(4) → Transcribe(5) → LLMTranslate(6) → SynthesizeSubtitleAudio(7) → GenerateMetadata(30) → AddWatermark(8，当前注释未启用) → SaveDatabase(9) |
| `DouyinChain` | `douyin_workflow.go` | Initialize(1) → ResolveDouyinShare(2) → DownloadDouyinVideo(3) → ExtractAudio(4) → Transcribe(5) → LLMTranslate(6) → GenerateMetadata(30) → SynthesizeSubtitleAudio(7) → SaveDatabase(9) |
| `BilibiliChain` | `bilibili_workflow.go` | GenerateMetadata(30) → UploadToBilibili(100)；通过 `group:"bilibili_steps"` 独立分组 |

步骤名常量集中在 `step_names.go`，供重试接口、前端展示、测试统一引用。

### 5.6 ProcessingService（跨链编排）

`processing_service.go` 是 Handler 与工作流之间的门面：

- `DetectPlatform` / `ResolveRemoteVideoTarget`：正则识别 YouTube / 抖音链接，抖音额外调用 TikHub 解析分享。
- `EnqueueRemoteVideoProcessing`：信号量（`Workflow.MaxConcurrent`，默认 4）限流 + goroutine 异步执行，单任务 30 分钟超时，注册到 `TaskRuntimeRegistry` 支持取消。
- `CancelTask`：通过 `TaskRuntimeRegistry` 取消在跑任务，并将视频状态置为 `paused`。
- `SubmitToPipeline` / `SubmitToPipeline`：对外暴露流水线提交入口。
- 用户级覆盖：`resolveTranslationConfig` 会从 `UserSettingsClient` 读取源语言/目标语言/模型，覆盖全局配置。

### 5.7 断点续跑与单步重试

`YouTubeChain` 提供三种恢复手段，是系统可靠性的关键：

- `ResumeProcessing`：从 DB 与磁盘重建 `VideoContext`，已完成步骤保留，其余重置后重跑；`findLocalVideoFile` 会在 `downloadDir/{videoID}/` 中自动定位视频文件。
- `RetryStepByName`：只重跑指定步骤（先按名称在链中查找），从 DB + 已保存 SRT 重建最小上下文；下载步骤若本地文件仍在则直接复用。
- `restoreTranscriptFromSavedSubtitles` / `restoreSubtitleAudiosFromSavedSubtitles`：按候选路径打分（`scoreTranscriptSubtitlePath`）挑选正确的字幕文件重建转录结果与配音输入，避免重复调用 ASR/TTS。
- `resolveVideoURL`：`video.URL` 若因历史原因存的是本地路径，可从 yt-dlp 命名文件（`%(id)s.%(ext)s`，11 位 YouTube ID）反推原始 URL。

---

## 6. 数据流：一次完整的搬运任务

```
用户提交链接 (web / API)
   │
   ▼
VideoProcessHandler
   │ DetectPlatform + ResolveRemoteVideoTarget（抖音走 TikHub）
   ▼
ProcessingService.EnqueueRemoteVideoProcessing  ── 信号量限流、注册可取消
   │
   ▼
YouTubeChain / DouyinChain .ProcessContextWithTracking
   │ 应用用户设置 + 偏好
   ▼
Chain.Run（ProgressTracker 逐步落库）
   │
   ├─ 1  Initialize       解析视频 ID、准备目录
   ├─ 2  DownloadVideo    yt-dlp（可带 cookies / proxy）
   ├─ 3  DownloadThumbnail
   ├─ 4  ExtractAudio     ffmpeg 抽音轨
   ├─ 5  Transcribe       Bcut / Whisper ASR → Transcript
   ├─ 6  LLMTranslate     BatchTranslator（分批 + 并发 + 上下文窗口）
   ├─ 7  SynthesizeSubtitleAudio  TTS 逐条合成
   ├─ 30 GenerateMetadata LLM 生成标题/简介/标签
   └─ 9  SaveDatabase     落库 tb_videos + 字幕文件
   │
   ▼
（用户审片：字幕编辑 / 配音调整 / 音画同步播放）
   │
   ▼
UploadToBilibiliHandler → BilibiliChain.Run
   ├─ GenerateMetadata（可覆盖）
   └─ UploadToBilibili（投稿 + 字幕补传，凭据来自 tb_account_bindings）
   │
   ▼
background.CronJob 定时扫描：自动投稿（1min）/ 字幕补传（5min）/ Feed 同步
```

---

## 7. 工具层（`pkg/tools`）

每个工具实现统一接口并注册进 `ToolRegistry`，同时被两类调用方复用：**工作流 Step** 与 **Agent 工具集**。

| 类别 | 文件 | 说明 |
| --- | --- | --- |
| 下载 | `download_video.go`、`download_thumbnail.go`、`douyin_download_video.go`、`douyin_fetch_video.go` | yt-dlp / TikHub 封装 |
| 音视频处理 | `extract_audio.go`、`transcode_video.go` | ffmpeg 封装 |
| ASR | `asr_engine.go`、`asr_bcut.go`、`asr_whisper.go`、`bcut_transcriber.go` | 双引擎可切换 |
| 翻译 | `translator.go`、`batch_translator.go`、`llm_batch_translator.go`、`llm_subtitle_translator.go` | 批量并发翻译，含上下文窗口 |
| TTS | `tts_engine.go`、`tts_client.go`、`tts_azure.go`、`tts_tencent.go`、`tts_edge.go`、`tts_openai.go` | 多厂商 + 音色目录 |
| 图像 | `image_generator.go`、`image_prompt.go` | 封面/配图 |
| 数据/业务 | `sql_database.go`、`video_query_tool.go`、`subscription_tool.go`、`user_settings.go` | Agent 可用的 DB 操作 |
| 编排 | `submit_pipeline_tool.go`、`rewrite_metadata_tool.go`、`subtitle_tool.go` | 供 Agent 驱动流水线 |
| 其他 | `api2key_chat_client.go` | 代理式 Chat 客户端 |

注册入口：`internal/bootstrap/tools_wiring.go` 的 `ToolsModule`，最终以 `group:"tools,flatten"` 注入 `pkg/agent`（Eino）。

---

## 8. 外部集成

| 能力 | 配置段 | 实现 |
| --- | --- | --- |
| LLM（翻译 / 对话分离） | `[translation]`、`[chat]`、`[llm]`（兼容回退） | `pkg/llm`，`AppConfig.ResolveTranslationProvider()` / `ResolveChatProvider()` |
| TTS | `[tts]`、`[azure_tts]` | `pkg/tools/tts_*`，音色目录见 `voices.json` / `azure_voices.json` |
| ASR | `[workflow]` | Bcut / Whisper |
| Bilibili 投稿 | 账号绑定表 + `[workflow].credentials_dir` | `pkg/bilibili`（`upload.go`、`subtitle.go`、`credential_file.go`、`crypto.go`、`zones.go`） |
| 抖音解析 | `[tikhub]` | `pkg/tikhub` |
| YouTube OAuth | `[youtube]`（client_id / secret / redirect_url） | `internal/service/youtube_client_factory.go`、`youtube_binding_service.go` |
| 飞书机器人 | `[feishu]` | `internal/handler/feishu_handler.go`（`/webhook/feishu`） |
| 服务端鉴权 | `[api_auth]`（AppID/AppSecret/Cookies 解密） | `internal/middleware/auth.go` |
| 埋点 | `[analytics]` | `internal/analytics` |
| 自更新 | `[updater]` | `internal/updater`（应用 + yt-dlp） |
| License / 会员 | `[license]` | `internal/service/license_client.go`、`activation_handler.go` |

**多 LLM  Provider 设计**：`translation` 与 `chat` 互相独立，各自配置 provider / model / base_url / api_key / temperature / max_tokens / timeout；未配置 translation 时回退到 chat（`provideLLMBatchTranslatorTool`）。

---

## 9. 数据模型与存储

`pkg/store` 基于 GORM，支持 **MySQL / PostgreSQL**（`database.go`），启动时执行 `MigrateDatabase` → `AutoMigrate` → 补列修正 → 种子数据（首个 `admin` 用户）。

核心表（`pkg/store/model/`）：

| 模型 | 文件 | 用途 |
| --- | --- | --- |
| `User` / `UserToken` / `UserPreference` / `UserSettings` | `models.go`、`user_settings.go` | 用户与个性化配置 |
| `Video` | `models.go` | 视频主记录（含 `tb_videos` 状态机） |
| `TaskStep` | `task_step.go` | 任务链步骤进度 |
| `VideoStatus` | `video_status.go` | 视频状态常量 |
| `Channel` / `TbSubscription` | `tb_channel.go` | 频道与订阅 |
| `AccountBinding` | `account_binding.go` | B 站 / YouTube 账号绑定（加密凭据） |
| `BiliSubtitleUpload` | `bili_subtitle_upload.go` | B 站字幕上传状态 |
| `SystemSettings` | `system_settings.go` | 系统级设置 |
| `UserAPIKey` / `UserMembership` / `LicenseActivation` / `Tier` | 同名文件 | 计费、会员、License |
| `AgentClient` / `AgentOpen` 相关 | `agent_open.go` | 第三方 Agent 应用、API Key、请求日志、异步作业 |

状态持久化由 `ProgressTracker` + `video_status.go` 共同驱动，配合 `MarkVideoStopped` 处理用户主动停止。

---

## 10. HTTP API 全景

路由集中注册在 `internal/handler/router.go`（`registerRoutes` 通过 `fx.In` 一次性收集所有 Handler，取代早期散落的 `fx.Invoke`）。

| 前缀 | Handler | 说明 |
| --- | --- | --- |
| `/health`、`/api/v1/system/usage` | `health_handler.go` | 健康检查与资源占用 |
| `/swagger/*any` | `swagger_handler.go` | Swagger UI |
| `/auth/*` | `local_auth_handler.go` | 本地 JWT 登录 |
| `/api/user/*` | `user_handler.go` | 用户信息 |
| `/api/v1/videos/*` | `video_handler.go`、`video_process_handler.go` | 视频 CRUD、提交处理、重试、续跑、停止 |
| `/api/v1/translate/*` | `translate_handler.go` | 字幕翻译 |
| `/api/v1/tts/*` | `tts_handler.go` | TTS 音色与合成 |
| `/api/v1/*`（字幕） | `subtitle_handler.go` | 字幕读写（支持 Cookie 解密中间件） |
| `/api/v1/bili-accounts/*` | `bili_account_handler.go` | B 站账号管理 |
| `/api/v1/upload/*` | `upload_to_bilibili_handler.go` | 手动投稿 |
| `/api/v1/bindings/*` | `account_binding_handler.go` | 账号绑定 |
| `/api/youtube/*`、`/api/v1/*` | `youtube_handler.go` | YouTube OAuth、频道、Feed |
| `/api/v1/*`（cookies） | `cookies_handler.go` | Cookies 管理 |
| `/api/v1/activate/*` | `activation_handler.go` | License 激活 |
| `/api/v1/updater/*` | `updater_handler.go` | 版本与自更新 |
| 动态 `basePath` 分组 | `user_settings_handler.go`、`system_settings_handler.go` | 用户/系统设置 |
| `/api/*` | `agent_handler.go` | 内置 Agent 对话 |
| `/agent/v1/*` | `agent_open_handler.go` | 第三方 Agent 开放 API（API Key + 限流） |
| `/webhook/feishu` | `feishu_handler.go` | 飞书事件回调 |
| `NoRoute` | `server/static.go` | SPA 静态托管兜底 |

**鉴权策略**（`registerRoutes`）：

- `[auth].users` 非空 → 本地 JWT（`AnyAuthMiddleware`）。
- 否则 `[api_auth]` 三项齐全 → AppID/AppSecret 中间件。
- 部分 Handler 额外支持 Cookies 解密中间件。

---

## 11. 前端架构（`web/`）

### 11.1 目录

```
web/src/
├─ app/                     Next.js App Router
│  ├─ layout.tsx / page.tsx / globals.css
│  ├─ login/ register/ verify-email/ auth/ account/
│  └─ dashboard/
│     ├─ layout.tsx  page.tsx        （总览，含任务队列）
│     ├─ tasks/      videos/         （任务 / 视频管理）
│     ├─ accounts/                   （B 站 / YouTube 账号绑定）
│     ├─ settings/                   （系统 + 用户设置，最大页面）
│     ├─ assistant/                  （AI 助手对话）
│     ├─ subscribe/                  （频道订阅）
│     ├─ extension/                  （浏览器扩展相关）
│     └─ profile/
├─ components/
│  ├─ ui/                            Button/Card/Input/Modal/Skeleton/StatusBadge
│  ├─ membership/                    会员与积分卡片
│  ├─ tts/VoicePicker.tsx            音色选择
│  ├─ task-quere/TaskQueueStats.tsx  任务队列统计（核心看板）
│  ├─ VideoPlayerModal.tsx           音画同步播放器弹窗
│  ├─ LocalVideoUpload.tsx           本地视频上传
│  ├─ BilibiliAccountManager / BilibiliBindDialog / CookiesManager
│  ├─ PageAgentProvider.tsx          页面智能体
│  └─ UpdateManager.tsx / ErrorBoundary / LanguageSwitcher
├─ lib/
│  ├─ api-client.ts                  Axios 实例 + 拦截器（自动解包 {code,data,message}）
│  ├─ api.ts / api/                  业务 API 模块（agent、api-keys、assistant-history、
│  │                                 system-settings、updater、user-settings）
│  ├─ backend-url.ts                 后端地址解析
│  ├─ video-player/                  video-sync-player、subtitle-timeline、
│  │                                 timeline-audio-preloader（字幕/配音同步播放）
│  └─ i18n.ts / utils.ts / video-paths.ts / video-submission.ts / project-id.ts ...
└─ hooks/                            useUserSettings、useMembership、useBilibiliAccounts、
                                     useAiModelCatalog、useUserPreferenceSync
```

### 11.2 与后端交互

- `getBackendBaseUrl()` 决定 baseURL；生产走同源（Go 静态托管），开发通过 `next.config*.js` 的 `rewrites` 把 `/api/*`、`/static/*` 代理到 `http://localhost:8096`。
- `APIClient` 在请求拦截器注入 `Bearer <token>`，响应拦截器自动把 `{code, data, message}` 解包为 `data`。

### 11.3 构建与托管

两种形态：

1. **一体化（默认）**：`make web-export` 导出静态产物到 `internal/server/out/`，Go 侧 `//go:embed all:out` 嵌入二进制，`ServeStaticWeb` 通过 `gin` 提供文件 + SPA fallback。开发模式（`debug=true`）下跳过托管，前端独立 `npm run dev`。
2. **Docker standalone**：`next.config-prod.js` 启用 `output: 'standalone'`，配合 `docker/Dockerfile` 独立部署前端。

---

## 12. 配置体系

单一 `config.toml`（示例见 `config.toml.example`、`docker/config.toml.example`），顶层分段：

```
[server] [database] [auth] [workflow] [api_auth] [analytics] [updater] [license]
[translation] [chat] [llm] [deepseek]      # LLM（翻译/对话分离，llm/deepseek 为兼容回退）
[tts] [azure_tts] [tikhub] [feishu] [youtube] [agent] [agent_open_api]
```

`[workflow]` 关键项：下载目录、cookies 目录/文件、凭据目录、`yt-dlp`/`ffmpeg` 路径、代理、LLM 翻译开关与批大小/并发/上下文窗口、源/目标语言、`max_concurrent`。

设计要点：**大量依赖都是可选的**。LLM 未配置时翻译/元数据生成步骤降级为跳过或回退；TTS 未配置时配音步骤不执行；fx 中的 `optional:"true"` 与 `ProvideAgent` 返回 `(nil, nil)` 共同保证「配置不全也能启动」。

---

## 13. 构建与部署

```bash
cp config.toml.example config.toml

# 开发：前后分离
go run main.go          # 后端 :8096
cd web && npm run dev   # 前端 :3000（rewrites 代理 /api 到后端）

# 生产一体化
make build              # = web-export + go build → ./ytb2bili
make build-all          # 多平台交叉编译到 bin/
```

- `Makefile` 通过 `-ldflags` 注入版本信息到 `internal/updater.Version`。
- `docker/` 提供 Dockerfile、`docker-compose.yml`、`next.config-prod.js` 对应的 standalone 方案。
- `supervisor-deploy.sh` 用于进程守护式部署。

---

## 14. 关键设计决策

| 决策 | 取舍 |
| --- | --- |
| **fx 依赖注入 + group 收集步骤** | 新增步骤零侵入（追加构造函数即可）；代价是需要熟悉 fx 语义 |
| **Chain 串行 + 步骤级持久化** | 实现简单、进度可观测、天然支持断点续跑；吞吐不如并发流水线 |
| **`IsRequired()` 区分强弱步骤** | 封面、转写、翻译、配音失败不阻塞主流程，提高整体成功率 |
| **`StepSkippedError`** | 让「非致命错误」与「跳过」语义统一，链逻辑单一 |
| **翻译与对话 LLM 分离配置** | 可针对不同任务选择性价比最优的模型 |
| **字幕文件即事实来源** | 续跑/重试优先从磁盘 SRT 重建状态，避免重复消耗 ASR/TTS 额度 |
| **前端产物嵌入二进制** | 单文件分发、零部署依赖；开发模式自动降级为独立 dev server |
| **工具层双用** | 同一套 `pkg/tools` 同时服务工作流与 Agent，行为一致 |
| **外部进程依赖（yt-dlp/ffmpeg）** | 复用成熟生态；需要环境预装，`updater` 负责 yt-dlp 自更新 |

---

## 15. 待完善 / 注意点

- `internal/workflow/pipeline.go` 的 `Pipeline` 目前以空 handler 占位，`ProcessingService` 实际走 Chain；`SubmitToPipeline` 退化为 `ChainPipeline`，且 `case "douyin"` 分支误用了 `s.youtubeChain`（`processing_service.go:94`）。
- `AddWatermarkStep` 已在 YouTube / Douyin 模块中注释未启用，但实现保留在 `add_watermark_step.go`。
- `TranslateStep`（微软翻译）与 `DeepseekTranslateStep` 仍保留在代码中，但模块注册的是 `NewLLMTranslateStep`；`deepseek_translate_step.go` 与 `llm_translate_step.go` 使用了相同的步骤名常量 `StepNameLLMTranslate`。
- `sql_database.go` 将 SQL 执行能力暴露给 Agent，对外开放 Agent API（`[agent_open_api]`）时需谨慎评估权限边界。
- `migrate.go` 中包含 MySQL 方言的裸 SQL（`ALTER TABLE ... MODIFY COLUMN` / `ADD COLUMN IF NOT EXISTS`），在 PostgreSQL 下会走「报错即忽略」分支，跨库兼容性需留意。
