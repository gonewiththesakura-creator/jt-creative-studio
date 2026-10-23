# 正式发布器适配会员上线后的拓扑（2026-10-23）

提交：`ae8fed7`（适配）、`c68ddb4`（按 Codex 审查修复）。`c68ddb4` 已用本发布器上线。

## 为什么要改

会员系统上线后，面板只监听服务器本机 `127.0.0.1:8189`，公网只有 nginx 的 80/443（`https://studio.dreamapi.club`）。
`membership_http.guard()` 让所有 `/api/*` 都要求已登录且 Host 为该域名，只豁免 `/api/live` 和仅限本机的
`/api/admin/release-drain`。会员开启时 `server.py` 的静态路由只公开 `app.html`、`app-manifest.json`、`favicon.png`
和 manifest 里的哈希资源。

旧发布器的第一步用 `http://8.210.125.65:8189/api/health` 判断空闲，得到 502，连 SSH 都没开始就停了。即使过了这一步，
换文件后的核验也都会失败并回滚：`/api/health`、`/api/workflows` 要登录；`/static/previews/` 和 `/static/style-configs.*.json`
对外是 404；realism 页标记已从 `/api/workflow-generate` 换成 `/api/image-edit-generate`；App Shell 构建里也没有
`style-retro-manga-luxury.webp` 字样（预览变成了哈希资源）。上一次成功的正式发布是 09-24。

## 现在怎么判断

| 检查 | 旧做法 | 现在 |
|---|---|---|
| 空闲 / 忙状态 | 连接前查公网 `/api/health` 三次 | pre-stop 先开启重启排空与进程内排空，再经 SSH 对回环 release-drain 重复 POST `enabled=true`（幂等），按原稳定窗口采样三项忙碌计数；任一忙即 `ReleaseBusyError`，走原准备期清理（关排空、撤重启排空、解锁）。排空时队列不启动新任务 |
| 存活 | 公网 `/api/live` | 不变（域名上的 `/api/live` 免登录） |
| DreamAPI 就绪 | 公网 `/api/health` 的 DreamAPI 字段 | `remote_dreamapi_runtime()` 以 root 读重启后面板进程的 environ，只回传"密钥是否存在 / 连接模式 / direct 端点是否合法"（照抄 `_dreamapi_request_endpoint` 规则）；不确定结果围栏用重启后排空状态的 `api_busy=false` 代替（`_running_job_id('api')` 把待定的 DreamAPI 任务算作 API 忙）。只接受 direct 模式 |
| 工作流名单 | 公网 `/api/workflows` | 已回读一致的 `config.json` 里的名称 |
| 前端字节 | `/`、`/realism`、旧预览、旧画风配置 | 一个绝对截止时间内逐字节核对 `/`、`/realism`、`/video`、manifest、全部哈希资源、gzip 的 `/?style=retro_manga_luxury`；画风触发词与 retro 预览经哈希资源核对 |
| 登录门 | 无 | 匿名 `/api/auth/me` 必须 enabled 且未登录；`/api/health`、`/api/workflows`、`/api/jobs` 必须 401；`/api/admin/release-drain` 的 GET 和不带凭据的空体 POST 都必须 404（面板自己会对 GET 回 404、对 POST 回 401，只有都 404 才说明 nginx 挡住了）。探测用 curl，墙钟上限、不跟随重定向、字节上限 |

`PUBLIC_BASE` 改为 `https://studio.dreamapi.club`。回滚路径仍用公网 `/api/live`。

## 审查与验证

- Codex 只读审查两轮（T261023-100151-996f、T261023-101319-8576）。第一轮两项 P2 均成立并已修：URL 解析异常可能把
  环境里的凭据经 stderr 带回（现在解析在保护块内，远端失败只返回固定文本）；只用 GET 证明不了代理挡住了 release-drain
  （现在 POST 也必须 404）。另采纳非阻塞建议：匿名探测改为有墙钟上限。第二轮结论"可以进入正式发布"。
- 完整测试门在 `c68ddb4` 上通过（657 秒），发布器内部又跑一遍后上线：`REALISM_RELEASE_DEPLOY_OK`。

## 已知局限

- 旧的 `--bootstrap-drain-contract` 路径（给没有排空接口的旧服务器）保持原样，仍依赖公网 health；生产已有排空合同，用不到。
- DreamAPI 若改成 workstation 模式，发布器会拒绝发布：那种模式的就绪是进程内的出口探测，只有需要登录的 health 能看到。
- `tools/` 下其余按功能发布脚本和大量历史核验脚本仍写死旧 IP 或依赖匿名 API，现在跑不通；在盘点和处置之前不要使用。
