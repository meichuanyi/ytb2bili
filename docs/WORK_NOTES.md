# ytb2bili 项目工作纪要

> 阶段：架构分析 → 登录链路验证 → 全面代码审计 → 鉴权修复方案 → 编译与冒烟验证
> 环境：Linux 容器，`/root/projects/ytb2bili-main`（源码），数据库用本地 MySQL 容器
> 日期：2026-09-05

---

## 1. 架构概览

| 层 | 目录 | 说明 |
|---|---|---|
| 入口 | [main.go](file:///root/projects/ytb2bili-main/main.go) | `bootstrap.NewApp()` → fx 启动 |
| DI 框架 | `go.uber.org/fx` | 全部模块按 fx 依赖注入装配 |
| 配置 | [internal/config](file:///root/projects/ytb2bili-main/internal/config) | BurntSushi/toml 解析，无 viper；[config.go](file:///root/projects/ytb2bili-main/internal/config/config.go) 提供默认配置；[app_config.go](file:///root/projects/ytb2bili-main/internal/config/app_config.go) 含 DSN 生成、YouTube 凭据、`applyEnvOverlay` 环境变量覆盖 |
| 路由 | [internal/handler/router.go](file:///root/projects/ytb2bili-main/internal/handler/router.go) | 集中注册入口 `registerRoutes`，20+ handler 由 fx 注入 |
| 服务 | [internal/service](file:///root/projects/ytb2bili-main/internal/service) | YouTube 绑定、B 站绑定、视频、订阅等业务逻辑 |
| 工作流 | [internal/workflow](file:///root/projects/ytb2bili-main/internal/workflow) | YouTube/B 站/抖音三套 pipeline，分阶段 step 组装 |
| 存储 | [pkg/store](file:///root/projects/ytb2bili-main/pkg/store) | GORM + MySQL/PostgreSQL |
| 工具 | [pkg/llm](file:///root/projects/ytb2bili-main/pkg/llm) | eino 封装的多厂商 LLM 客户端 |
| HTTP | [internal/server](file:///root/projects/ytb2bili-main/internal/server) | Gin 引擎装配、静态资源 embed |

**鉴权双模式**（配置决定）：

- `[auth].users` 非空 → `LocalAuth`：`/auth/login` 邮箱密码换 JWT（`AnyAuthMiddleware` 解析 Bearer）。
- 否则 `[api_auth]`（默认 `enabled=true`, appsecret `ytb2bili_secret_2026`）→ `NewAuthMiddleware`。

**路由装配逻辑**（[router.go L58-71](file:///root/projects/ytb2bili-main/internal/handler/router.go#L58-L71)）：`authMid` 只在上述两种模式之一满足时才非 nil；大量 handler 注册时**没有把 `authMid` 传进去**，形成鉴权缺口。

---

## 2. 登录链路验证结论

### 2.1 后端本地登录（可用，已验证）

- 路由：`POST /auth/login`（**不带** `/api/v1` 前缀），请求体 `{email, password}`。
- 验证结果：返回 `{code:200, data:{accessToken, refreshToken, expiresIn, user}}`。
- `GET /auth/me` 需 `Authorization: Bearer <token>`，无 token 返回 401。✅
- 注册默认关闭（`registerDisabled`）。

### 2.2 B 站扫码登录（问题已定位）

- **非代码 bug**：容器内 DNS 解析坏了。日志：

  ```
  dial tcp: lookup passport.bilibili.com on [::1]:53:
  read udp [::1]:52098->[::1]:53: read: connection refused
  ```

  旧容器的 `/etc/resolv.conf` 指向宿主残留 DNS `[::1]:53`，而容器内无本地 DNS。属环境问题，非 ytb2bili 代码缺陷。换用正确 DNS 的容器/主机即可。

### 2.3 YouTube OAuth 登录（未完成真实验证）

- **阻塞点**：需要真实 Google OAuth 凭据（`[youtube] client_id / client_secret`），或提供可用的代理路由（如 `host.docker.internal:7890`）转发到 `accounts.google.com`。
- 代码层面发现的问题见 §3.1。

### 2.4 前端登录方式（供 Web 联调）

- 前端 `web/`（Next.js 14）`AuthContext` 中 Firebase 登录已废弃（`isFirebaseConfigured=false`），**邮箱登录 `emailSignIn` 走后端 `/auth/login`**。
- API 地址逻辑 `web/src/lib/backend-url.ts`：未设 `NEXT_PUBLIC_API_URL` 时同源；dev 联调需设 `NEXT_PUBLIC_API_URL=http://localhost:8096`（后端 CORS 已放开任意 Origin，[cors.go](file:///root/projects/ytb2bili-main/internal/middleware/cors.go) 动态回显）。
- dev server 默认 3000，被占用会自动切 3001。

---

## 3. 代码审计问题清单（含鉴权缺口）

> 均未修改代码。修复方案见 §4。

### 3.1 YouTube handler —— 路由完全不鉴权

文件：[internal/handler/youtube_handler.go](file:///root/projects/ytb2bili-main/internal/handler/youtube_handler.go)

- `RegisterRoutes` L1335 中挂 auth 的代码被注释掉（L1336-1339），`/api/youtube/*`（L1342-1358）与 `/api/v1/youtube/*`（L1361-1383）全部公开：search/trending/recommended/categories、feed 刷新、订阅查询/同步、OAuth callback 等。
- `CheckAuthStatus` L361：只要 query `user_id` 非空就返回 authorized，**不查库**。
- `GetLatestVideos` L616：`user_id` 为空时不按用户过滤，返回全量视频。
- `GetUserTbSubscriptions` L1036 / `SyncUserTbSubscriptions` L1189：直接信任客户端传的 `user_id`/`access_token`。
- `UpdateTbSubscriptionStatus` L1120：请求体 `req.UserID` 与记录一致即可改，无认证也放行。
- `OAuthCallback` L109：外部 `state` 当作 `qrCodeKey` 从全局 `sharedBindingCache` 取 userID 并保存绑定，无发起者一致性校验。
- service `CompleteOAuthBinding`（youtube_binding_service.go L34）：userID 外部传入，无当前登录用户比对。

### 3.2 AccountBinding handler —— 完全信任客户端 user_id

文件：[internal/handler/account_binding_handler.go](file:///root/projects/ytb2bili-main/internal/handler/account_binding_handler.go)，group `/api/v1/bindings`（L88-101）无中间件：

- `POST /qrcode`：body 里 `user_id` 直接绑定。
- `GET /list`：query `user_id` 非空即返回该用户绑定列表。
- `DELETE /:id`：只按 id 删，无 user 校验。
- `PUT /:id/primary`：请求体 `req.UserID` 客户端自报。
- `GET /youtube/authorize` / `GET /youtube/callback`：按 query userID/state 缓存操作。
- `POST /youtube/complete`：stub，返回 “bridge removed”。

### 3.3 Cookies handler —— 全局路径，无归属

文件：[internal/handler/cookies_handler.go](file:///root/projects/ytb2bili-main/internal/handler/cookies_handler.go)，`/api/v1/cookies`（L28-37）公开：`POST /upload`、`GET /status`、`DELETE /`。全部操作固定全局 `cookiesPath`（L225-231），非 per-user。

### 3.4 Updater handler —— 公开且含高危动作

文件：[internal/handler/updater_handler.go](file:///root/projects/ytb2bili-main/internal/handler/updater_handler.go)

- L193-207 注释明示“所有接口均为公开”。`GET/POST /api/v1/updater/version|check|update|status`。
- `POST /update` 的 `DoUpdate`（L104）注释“应加管理员检查”但**未实现** —— 任意访问者可触发自身更新，风险高。

### 3.5 Video handler —— 部分有 auth，但无归属一致性

文件：[internal/handler/video_handler.go](file:///root/projects/ytb2bili-main/internal/handler/video_handler.go)

- 公开组 `/api/v1/videos`（L69-79）：POST/GET 列表/counts/`GET :id`/`GET :id/events`/`GET :id/file`/PUT/DELETE 全部无鉴权。`authGroup`（L80-87）只有 retry/upload-bilibili/resume/stop。
- `listVideos` L118 / `taskCounts` L105：query `user_id` 直接查，可看任意用户数据。
- `getVideo`/`updateVideo`/`deleteVideo`/`serveVideoFile`：只按 id 操作，无归属校验 → IDOR。

### 3.6 其它无鉴权注册

- [agent_handler.go](file:///root/projects/ytb2bili-main/internal/handler/agent_handler.go) `POST /api/agent/run` 无 auth；`getUserIdentity` uid 为空仍继续（Free tier）。
- [upload_to_bilibili_handler.go](file:///root/projects/ytb2bili-main/internal/handler/upload_to_bilibili_handler.go)：注册无中间件，handler 内 `c.Get("uid")` 取不到即 401 —— 依赖引擎侧是否有 uid 注入，实际无。
- [subtitle_handler.go](file:///root/projects/ytb2bili-main/internal/handler/subtitle_handler.go)：`POST /api/v1/submit` 只挂 cookie 解密中间件，无认证。
- [activation_handler.go](file:///root/projects/ytb2bili-main/internal/handler/activation_handler.go)：`/api/v1/activate` 公开。
- [translate_handler.go](file:///root/projects/ytb2bili-main/internal/handler/translate_handler.go)：`POST /api/v1/translate/subtitles` 公开（router.go L103-104 手动注册）。
- [tts_handler.go](file:///root/projects/ytb2bili-main/internal/handler/tts_handler.go)：`GET /api/v1/tts/voices` 公开（合理），`POST /preview` 有 auth。

### 3.7 相对规范的部分（参考样板）

- [bili_account_handler.go](file:///root/projects/ytb2bili-main/internal/handler/bili_account_handler.go)：`BiliAccount` 由 router 传 `authMid`，且 handler 内先 `c.Get("uid")`，再 `GetUserBiliAccounts(uid)` 确认归属后才删/改 —— **是修复其它 handler 的样板**。
- [user_handler.go](file:///root/projects/ytb2bili-main/internal/handler/user_handler.go)、[system_settings_handler.go](file:///root/projects/ytb2bili-main/internal/handler/system_settings_handler.go)、[user_settings_handler.go](file:///root/projects/ytb2bili-main/internal/handler/user_settings_handler.go)：自建 auth 中间件挂在 group。
- [agent_open_handler.go](file:///root/projects/ytb2bili-main/internal/handler/agent_open_handler.go)：APIKeyAuth + scope 鉴权规范。

---

## 4. 鉴权修复方案（已交付，未实施）

> 用户决策：**保留 query/body 兼容（不做破坏性收紧），只加鉴权**。

### 4.1 方案原则

1. **所有“用户数据访问/变更”路由默认加鉴权**（`AnyAuthMiddleware` 或 `authMid`），未认证 401。
2. **保留旧客户端传 `user_id` 的兼容能力**：认证通过后，若请求带 `user_id` 且等于认证 uid 才采信；带别的 `user_id` 拒绝；不带则回退认证 uid。即“query 值仅作为透传，不作为权限来源”。
3. 认证失败 / 归属不一致 → 统一 401/403，不泄漏数据。

### 4.2 逐文件动作

| 文件 | 动作 |
|---|---|
| [router.go](file:///root/projects/ytb2bili-main/internal/handler/router.go) | `authMid` 传给 `YouTube.RegisterRoutes(r, authMid)`；`AccountBinding/Cookies/Updater/UploadToBilibili/Subtitle/Agent/Activation/Translate` 全部改传/挂 authMid（内部再区分公开子集）。抽一个 `resolveUserID(c)` 辅助函数，实现“auth uid 优先 + query/body user_id 一致性校验”。 |
| [youtube_handler.go](file:///root/projects/ytb2bili-main/internal/handler/youtube_handler.go) | 恢复 L1336-1339 注释掉的 auth 挂载；`GetLatestVideos`/`GetUserTbSubscriptions`/`SyncUserTbSubscriptions`/`UpdateTbSubscriptionStatus`/`CheckAuthStatus` 用 `resolveUserID` 替换裸 query 取值。公开子集（search/trending/video 详情等）单独放行。 |
| [account_binding_handler.go](file:///root/projects/ytb2bili-main/internal/handler/account_binding_handler.go) | group 挂 authMid；qrcode/list/primary/refresh/unbind 全部走 `resolveUserID`；QR 缓存键绑定认证 uid，poll 时校验归属。 |
| [cookies_handler.go](file:///root/projects/ytb2bili-main/internal/handler/cookies_handler.go) | 挂 authMid（cookie 是全局共享资源，至少要求登录），并考虑 per-user 拆分或管理员角色校验。 |
| [updater_handler.go](file:///root/projects/ytb2bili-main/internal/handler/updater_handler.go) | `version/check/status` 保留公开；`POST /update` 挂 authMid 且仅 admin 角色放行。 |
| [video_handler.go](file:///root/projects/ytb2bili-main/internal/handler/video_handler.go) | 公开组移到 `authGroup`（list/get/update/delete/file/counts 全部要求认证），查询/操作按认证 uid 过滤，删除“user_id 裸传”路径；保留公开可配的下载文件白名单路由再评估。 |
| [agent_handler.go](file:///root/projects/ytb2bili-main/internal/handler/agent_handler.go) | `/agent/run` 挂 authMid；无 uid 则 401（不再按 Free tier 放行匿名）。 |
| [upload_to_bilibili_handler.go](file:///root/projects/ytb2bili-main/internal/handler/upload_to_bilibili_handler.go) | 注册时传 authMid，保证 `c.Get("uid")` 可靠存在。 |
| [subtitle_handler.go](file:///root/projects/ytb2bili-main/internal/handler/subtitle_handler.go) | `/api/v1/submit` 挂 authMid。 |
| [activation_handler.go](file:///root/projects/ytb2bili-main/internal/handler/activation_handler.go) | `activate` 挂 authMid（许可证激活按用户）；`status` 可保留公开。 |
| [translate_handler.go](file:///root/projects/ytb2bili-main/internal/handler/translate_handler.go) | 挂 authMid。 |
| [youtube_binding_service.go](file:///root/projects/ytb2bili-main/internal/service/youtube_binding_service.go) | `CompleteOAuthBinding` 增加 `operatorUID` 参数并在 service 内校验与 target 一致。 |

### 4.3 遗留修复项（非鉴权，需单独立项）

1. **Postgres 不兼容**：`pkg/store/migrate.go` 使用 MySQL 专属 SQL（`MODIFY COLUMN ... MEDIUMTEXT`、`TINYINT(1)`）；model 中 `mediumtext`、`datetime` 类型 tag 在 postgres 下 AutoMigrate 会失败（启动时报 `type "mediumtext" does not exist`）。当前项目实际以 MySQL 为“原生”DB。
2. **LLM 配置为启动硬依赖**：[tools_wiring.go L38-44](file:///root/projects/ytb2bili-main/internal/bootstrap/tools_wiring.go#L38-L44) `provideChatLLMClient` 要求 `[chat]`/`[llm]` 有效，否则 fx 启动失败（错误 `对话 LLM 未配置`）。`IsValid()` 逻辑在 [pkg/llm/provider.go L53-63](file:///root/projects/ytb2bili-main/pkg/llm/provider.go#L53-L63)：openai 等需非空 api_key；ollama 只需 base_url。
3. **embed 目录坑**：[internal/server/static.go L18](file:///root/projects/ytb2bili-main/internal/server/static.go#L18) `//go:embed all:out` 在目录不存在/为空时**直接编译失败**（注释声称“警告不失败”是错的）。已放 `.gitkeep` 占位；要跑 go build 必须保留该目录非空。

---

## 5. 编译与冒烟验证记录

### 5.1 结论

后端在 **MySQL 上可完整启动**：fx 全模块装配成功，HTTP 监听 `8096`，健康检查、登录、鉴权接口全部符合预期。

### 5.2 关键环境事实（重要，避免重复踩坑）

| 项 | 事实 |
|---|---|
| 宿主机 | **没有 Go**（`which go` 为空），但有 node/npm、ffmpeg(`/usr/bin/ffmpeg`)、yt-dlp(`/usr/local/bin/yt-dlp`) |
| Go 编译 | 借 `golang:1.24-alpine` 容器编译为静态二进制（CGO_ENABLED=0），放回宿主机运行。**容器内每次全量下载 go module 会较慢**（本项目依赖多，首次约需几分钟，中途易被误判卡死） |
| MySQL | 本机容器 `ytb2bili-mysql`（`mysql:8.0`），映射宿主机 `127.0.0.1:3306`；项目初始化库 `ytb2bili` 用户密码 `ytb2bili@123` |
| Postgres | 本机 `127.0.0.1:5435` 可用，但**项目 migration 与 postgres 不兼容**（见 §4.3-1） |
| 容器网络 | 旧容器 DNS 指向 `[::1]:53` 导致解析失败（见 §2.2）；本次 go build 的容器网络正常 |
| 前端 | Next.js dev 跑通，`npm ci` 606 包约 17s；dev 端口 3000 被其它 docker 占用会自动切 3001 |

### 5.3 冒烟测试明细（全部通过）

| 验证项 | 命令 / 结果 |
|---|---|
| 编译 | `go build -o ytb2bili .` 成功，二进制 ~79MB |
| 启动 | fx 全模块 RUN，`http server starting addr 0.0.0.0:8096`，定时任务 4 个 cron 启动 |
| DB 迁移 | MySQL AutoMigrate + 种子数据成功 |
| `GET /health` | `{"ok":true,"version":"dev",...}` |
| `POST /auth/login` | 200，返回 accessToken/refreshToken/user |
| `GET /auth/me` 带 token | 200，返回 admin 用户 |
| `GET /auth/me` 无 token | 401 |
| `GET /api/v1/videos`（带 token） | 200 |
| 测试账号 | admin@126.com / 123456（config.toml `[[auth.users]]`） |

### 5.4 本机复现步骤（供后续使用）

```bash
# 0) 依赖：MySQL 容器在 127.0.0.1:3306，确认 config.toml 配置正确
# 1) 编译（宿主机无 go，用容器；输出在 /root/projects/ytb2bili-main/ytb2bili）
docker run --rm -v /root/projects/ytb2bili-main:/workspace -w /workspace golang:1.24-alpine \
  sh -c 'go build -o ytb2bili .'

# 2) config.toml 需满足 LLM 校验才能启动（可先填占位 key，冒烟不触发真实调用）
# 3) 宿主机直接运行（勿再套 docker run 跑二进制）
cd /root/projects/ytb2bili-main && ./ytb2bili

# 4) 验证
curl -s http://127.0.0.1:8096/health
curl -s -X POST http://127.0.0.1:8096/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@126.com","password":"123456"}'

# 5) 前端（可选，web/ 下 node_modules 已装）
cd web && NEXT_PUBLIC_API_URL=http://localhost:8096 npm run dev   # 默认 3000，占用则 3001
```

### 5.5 环境残留（需用户决定清理）

| 残留 | 说明 | 是否影响 |
|---|---|---|
| 二进制 `/root/projects/ytb2bili-main/ytb2bili` | 冒烟后删除过一次；如需再复现请重编 | 无（已删/未生成） |
| Docker 容器 `ytb2bili-mysql` | 冒烟用的 MySQL（3306） | **验证仍需，勿删** |
| `config.toml` | 为测试创建；`[llm].api_key` 已还原为空（不改则不能通过 LLM 启动校验） | 需填真实 key 才可再启动 |
| `internal/server/out/.gitkeep` | embed 编译必需占位文件 | 保留 |

---

## 6. 剩余待办 / 阻塞点

1. **鉴权修复实施**：按 §4.2 逐文件落地（方案已交付，代码未改）。
2. **YouTube 真实验证**：需要真实 Google OAuth client_id/client_secret（用户曾同意提供，尚未给到）。拿到后可配 `[youtube]` 或环境变量 `YOUTUBE_CLIENT_ID/SECRET/REDIRECT_URL` 复验。
3. **LLM 真实 key**：`[llm].api_key` 决定 pipeline（改写元数据/字幕翻译/智能体）能否真实跑通；占位 key 只能过启动校验。
4. **B 站扫码**：在 DNS 正常的网络环境复验二维码生成→轮询→绑定闭环。
5. **Postgres 兼容**（可选）：若需支持 postgres，改造 migrate.go 与 model 类型 tag。
