# App Shell 渐进优化交付（2026-09-21）

基线：`403503028928f80195a5a3c7cfd3795bccc630a0`，目标分支 `feat/singularity-workbench`。
初始优化阶段仅本地验证与 GitHub 提交。用户随后明确授权上线及真实生图/视频测试；
2026-09-21 正式发布 `962ece1`，上线补充见文末。

## 原架构与新架构

原来 `/`、`/realism`、`/video` 各加载完整 HTML、脚本和黑洞，切换销毁整个文档。
现在三个 URL 都由 `static/app.html` 提供统一导航与页面容器。Router 用 pushState/popstate
切换；每页首次进入挂载一次，随后隐藏/显示，保留 DOM、脚本闭包、表单、File/Blob、轮询与恢复状态。
采用 ShadowRoot 隔离重复 ID 和页面 CSS，不使用 iframe、eval 或运行时字符串函数。
隐藏页仍可查询已有任务；全局背景观察所有已挂载页的忙状态。

黑洞由 `frontend/main.js` 在 UI 配置可用、两次绘制机会之后通过 idle 回调导入，
`static/singularity/workbench.js` 是唯一 Renderer 创建位置。该模块由整个应用复用。
模块导入、WebGL、shader 和首次 composer.render 成功后设置 ready，950ms 渐显；切页不会重播。
配置等待最多 3 秒，失败时业务加载错误与重试仍可用。

## 权威源与文件职责

| 文件 | 职责 |
|---|---|
| `frontend/index.html`, `main.js` | 正式 Shell 与 UI 优先启动 |
| `frontend/router.js` | 懒挂载、Keep Alive、快速导航、Back/Forward、滚动位置 |
| `frontend/page-scope.js` | 页内 DOM 查询隔离，保留真实浏览器能力 |
| `frontend/api.js` | 仅对无附加认证参数的 GET /api/workflows 做 5 分钟内存缓存；失败清除，POST 不经过缓存 |
| `frontend/pages/creator/style-data.js` | 按画风加载、缓存、悬停预取、异步收藏恢复、防异步选择乱序 |
| `frontend/styles/app.css`, `page.css` | Shell、140ms 切页、首次光场渐显、大面板模拟玻璃 |
| `frontend/compile-page.mjs`, `imports.mjs` | 构建期 AST 识别模块依赖和隐式元素引用 |
| `tools/build_frontend.py` | 从三个 Builder 的输出生成独立 JS/CSS/片段、画风 JSON、预览资源与内容哈希 |
| `static/assets/*`, `app.html`, `app-manifest.json` | 正式生成物，不手改 |
| `server.py` | 仅改三条页面静态路由和 hash 资源 immutable 缓存头 |
| `static/singularity/workbench.js`, `appearance.js` | 常驻场景、跨 ShadowRoot 忙状态/预览、首帧指标、移动降载 |
| `tests/test_app_shell.py`, `tools/verify_app_shell.py` | 离线浏览器、真实本地 HTTP、无付费性能检查 |
| `frontend/verify-contracts.mjs` | 证明打包保持 157 个业务函数体一致 |
| `tools/deploy_realism_release.py` | 打包新资源，更新新增测试的清单摘要；付费证据门保留拒绝行为 |

三个旧 Builder 仍是业务内容权威源，保留原 HTML 作回归与回滚参照；本阶段不全面搬迁
旧模板或重写视频 `.replace()` 链。新增路由、配置加载、缓存与构建逻辑已有正式源目录。
CSS 虽外置下载，但为 ShadowRoot 隔离，在挂载时注入该页 style 节点；不是全局重新解析所有页面。
其他页空闲 4 秒后只预取模块/模板/CSS，进入时才运行初始化和业务恢复。

## 测量数据

环境：本机 Chromium 151，全部网络由 Playwright 本地资源/假 API 响应拦截。
数据是解压后的资源字节，非公网吞吐或 gzip 线速；单轮时间存在调度噪声。
页面计时测量关闭 WebGL；图形生命周期另用 SwiftShader 验证。

| 首次 Creator 资源 | 原版 | 新版 |
|---|---:|---:|
| 初始 HTML 文档 | 440,808 B | 1,688 B |
| HTML（含首个页面片段） | 440,808 B | 10,118 B |
| 外置业务 JS（原版主要内嵌） | 0 B | 52,209 B |
| CSS | 14,564 B | 62,548 B |
| 画风 JSON | 1,168,164 B | 104,145 B |
| 已完成下载的预览资源 | 164,736 B | 203,600 B |
| 上述合计 | 1,788,272 B | 432,620 B |

首屏上述资源减少约 **75.8%**；画风 JSON 减少 **91.1%**。
预览从内嵌拆为独立缓存资源，因此独立图片下载量略增；不是删除预览或隐藏成本。
整个延迟图形依赖仍约数 MB，未宣称整个会话流量减少相同比例。

| 时序（ms） | 390px 原/新 | 1440px 原/新 |
|---|---:|---:|
| DOMContentLoaded | 153.4 / 42.1 | 103.4 / 48.6 |
| 生成控件可用（代理可交互指标） | 195.0 / 160.2 | 143.9 / 160.3 |
| Creator → Realism（含自动化点击等待） | 82.9 / 64.8 | 78.8 / 63.8 |
| Realism → Video | 60.9 / 60.8 | 63.3 / 59.0 |
| Video → Creator | 107.2 / 40.8 | 101.1 / 43.8 |
| 同一轮文档请求数 | 4 / 1 | 4 / 1 |

新版首次模块切换内部耗时 20–37ms；已经挂载的三页内部切换约 1.1–2.5ms。
桌面首次可交互没有稳定改善，额外模块请求在本地无网络延迟下有开销；收益主要是减少
首次资源、支持缓存与取消重复初始化。这里不把 DOMContentLoaded 当成所有业务准备就绪。

| 图形指标 | 390px | 1000px |
|---|---:|---:|
| UI 控件可用 | 176.6ms | 171.2ms |
| Three import 开始 | 288.3ms | 206.1ms |
| Renderer 创建完成 | 398.5ms | 333.1ms |
| 首帧/ready | 518.7ms | 460.8ms |
| Renderer / WebGL Context | 1 / 1 | 1 / 1 |
| 初次 compileShader 调用 | 20 | 20 |
| 三页切换新增编译/Context | 0 / 0 | 0 / 0 |
| 软件渲染短样本 FPS | 7.86 | 9.97 |

20 次 shader 编译包含 bloom/output 多通道，不是 20 次黑洞初始化。
没有实体手机 GPU 占用、功耗、长时热降频数据；软件 FPS 不代表实体显卡指标。

## 手机与 GPU

保留原 20/30 FPS 上限、隐藏页暂停、减少动态效果、用户暂停、任务忙时暂停、
context lost/shader failure 静态降级。手机 DPR 上限从 1.25 改为 1，RenderTarget 去掉
MSAA，bloom 强度乘 0.8。像素预算仍为手机 550k / 桌面 1.4M（乘外观质量），
低性能时降至最低 300k；现在除 CPU 提交时间，也观察连续活动帧间隔。

创作和有结果的预览大面板用透明渐变/边框/内高光替代真实 backdrop blur；空预览保留
透明背景使黑洞可见。手机大面板较高不透明度。TopBar、小 Popover 和外观面板保留模糊；
外观透明度继续继承到页内，毛玻璃滑块对保留模糊的小区域有效。

## 验证与发布边界

- 55 个既有脚本合同 + 41 个 pytest 文件，543 项 pytest（含新增 Shell 回归）。
- Shell 浏览器覆盖手机/桌面无文档重载、三页状态、Back/Forward、直接入口刷新、
  场景导入失败、只加载当前画风、API 参数保持、历史按钮、外观继承、任务隐藏后继续轮询。
- 本地 HTTP 实测三路由返回 Shell，hash JS/CSS/HTML 片段为一年 immutable，Shell 为 no-cache。
- `verify_singularity_motion.mjs`、`verify_singularity_shader.py`、`verify_singularity_ui.py` 均保留并运行。
- 新 `verify_app_shell.py` 用真实 WebGL 验证单 Context、单 Renderer、编译不增加、
  hidden-page busy 暂停、reduced-motion，以及 UI 比图形先可用。
- 后端业务 AST 与基线一致，`config.json` 字节一致；不修改 workflow ID、请求参数、幂等、fence、jobs 格式。
- 完整测试发现上传临时文件 finally 清理与断言的时序竞争；测试客户端现在最多等待 2 秒
  观察文件清除，原有无临时残留断言保留，实际泄漏仍失败。未改上传流程。
- 初始旧付费 E2E 只认证历史运行版本，新 Shell 当时被正确拒绝。追加授权后，隔离实例
  完成真实 Image 2 测试并记录新证据；现在同时绑定后端及 Shell/全部 hash 资源摘要，
  测试覆盖历史正例、当前正例和后端/前端资源变更时拒绝。

## 构建、回滚与下一阶段

```powershell
npm ci --prefix frontend --ignore-scripts
python build_unified_three_styles.py
python build_realism_workbench.py
python build_video_workbench.py
python tools/build_frontend.py
node frontend/verify-contracts.mjs
python -m pytest -q tests/test_app_shell.py
python tools/verify_app_shell.py
python -c "from tools.deploy_realism_release import run_release_tests; run_release_tests()"
```

生成资源以 hash 命名，Git 属性固定原始字节，包含 Three MIT license。构建仅清理
`static/assets` 中自己生成且不再引用的旧 hash 文件，不清理运行服务器。
回滚用 `git revert <本次提交>`，基线 `4035030`；Git 回滚或 push 不会改变生产服务器。

下一阶段：真实手机/实体 GPU 与慢网多轮测量、公共 CSS 去重、把 Builder 的业务模板迁到
正式页面模块、逐步减少隐式 DOM 适配、公共 Gallery/Upload/TaskCard、统一任务 Store。
Keep Alive 会增加多页同时挂载后的内存占用，当前最多三页；保留上传 File/Blob 是刻意行为。
Vue/Vite 可在这些边界稳定后评估，本阶段未引入运行框架。

## 上线补充（2026-09-21）

### 2026-09-22 CSS 回归修复（仅 GitHub，未部署）

旧 html 背景经 scoped_css 转换后落到 Shadow host，遮挡全局 Canvas。
权威源 `frontend/styles/page.css` 为 `:host` 添加 `background:transparent!important`；
内层 body/app-shell 保持透明，空预览原有 7% 半透明底及 has-results 玻璃背景不变。
四步 Builder 已重新运行，三个页面 CSS hash 和 Shell/manifest 引用随构建更新。
新增离线真实 WebGL 浏览器回归，覆盖三页计算背景、单 Renderer、scene ready、
空预览 Canvas 层像素可见性及结果背景。未修改场景、Shader、外观参数或生成业务。
本修复不更新历史付费证据、不执行付费测试、不部署；既有生产证据绑定仍保留。

- 发布代码 `962ece1`，目标分支不变；未合并或修改默认分支。
- `tools/prepare_dreamapi_native_canary.py` 现在暂存完整发布资源，避免候选实例缺少 Shell。
- `tools/deploy_realism_release.py` 验证新三路由、manifest、全部延迟资源的精确字节，
  保留旧页面配置/画风合同检查。未更改生成 API 合同或付费重试。
- Image 2 任务 `b8be196da80c`，单次提交，109 秒，864×1536 PNG，视觉检查通过。
  证据：`audit/app_shell_canary_20260921/verification.json`。隔离候选实例已停止清理，产物保留。
- 完整发布门：55 个脚本合同检查（保留已锁定的历史预期失败）、41 个 pytest 文件/545 项测试。
  发布前验证与正式发布器内验证均通过。
- 首次 SSH 上传在暂存阶段连接被重置，确认线上未切换、备份为空及维护状态未开启后，
  仅解除归属明确的失败暂存事务锁。第二次正式事务成功，备份保存在服务器
  `.release-transactions/20260921T123907Z-6db735183040403394462a10e06e529e/backup`。
- 正式发布器返回 `REALISM_RELEASE_DEPLOY_OK`，维护模式已解除，ComfyUI 和 DreamAPI 健康检查通过。
- 浏览器公网实测：Creator → Realism → Video → Creator、Back/Forward，document=1、Renderer=1、scene=ready。
- 发现一次首屏样式加载失败，后续诊断请求均 200，浏览器复测通过；尚未定位瞬时网络失败根因。
  不把这次上线等同于解决所有上游限流/网络断连。
- `tools/verify_app_shell_live.py` 默认只读，真实短视频必须明确传入 `--paid-video`。
  提交前落盘状态，已有状态禁止重提；可用于以后人工授权后的上线冒烟测试。
- 真实视频任务 `2f785dfe4263`：MiniMax H3 文生/图生视频，512×512、请求 4 秒，单次提交，
  139.5 秒完成；切去 Creator 后继续执行，返回 Video 正常预览。另行验证媒体解码与播放：
  实际 512×512、4.458333 秒，播放时间前进、无媒体错误。状态查询曾返回一次 502，随后原任务查询成功。
