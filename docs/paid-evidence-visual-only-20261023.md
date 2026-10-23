# 付费证据放行纯视觉前端改动；低功耗黑洞（2026-10-23）

用户 10-23 授权："在付费证据校验里放行纯视觉前端改动（只允许样式表、黑洞场景及其渲染库、预览图变化，业务资源逐字节一致，
视觉脚本不得联网，后端规则不变）"。实现经 Codex 四轮只读审查后比授权更严：场景脚本不靠"不联网"判断，而是逐字节审查后固定。

## 规则（`tools/deploy_realism_release.py` 的 `visual_only_frontend_change()`）

付费 canary 证据（`audit/accretion_canary_20261022`）原先要求 App Shell 前端全部字节与测试时一致。现在前端漂移在以下条件
**全部**满足时也接受；后端（`server.py`、`config.json`、源页面等）的比较不变。

1. 业务资源（`main`、`router`、`api`、`account`、三个页面模块与结构、画风配置、`login-scene`、`accretion-layout` 等，即不匹配
   `VISUAL_FRONTEND_ASSET` 的全部资源）集合相同、逐字节相同。
2. `app.html` 与 manifest 把视觉资源文件名里的哈希抹掉后完全相同。
3. 两边都存在的同名视觉资源逐字节相同。
4. 新出现的**场景脚本**（workbench / shaders / appearance / three / 后处理）完整 sha256 必须在 `REVIEWED_VISUAL_SCRIPTS_SHA256` 里。
   脚本和业务代码在同一页面，不联网也能改业务 DOM、存储或全局函数，所以不能靠关键词判断；改场景脚本要先审查，再把新摘要加进这个集合。
   目前只固定了低功耗黑洞 `workbench.8c2d3015f7af.js`。
5. 新出现的**样式表**由 `css_fetch_targets()`（按 CSS Syntax 3 写的小词法器）读出全部 `url()` 目标：注释、字符串是独立状态；
   函数名不分大小写、URL 值保留原文；反斜杠转义、`@import`、`@charset`、CSS 空白以外的控制字节、UTF-16 BOM、
   `image-set`/`image`/`src`/`cross-fade`/`element`、未闭合的字符串或注释都按"读不准"拒绝。每个目标只能是 `data:` 或付费测试时
   样式表已经引用过的原文目标。
6. 预览图（webp）、许可证文本可以随意变化。

任何一条不满足 → 仍报 `native DreamAPI frontend payload drift`，需要新的付费 canary 或审查例外。

## 审查记录

- T261023-141048-f7f7：禁用词判断脚本不可靠（脚本可不联网改业务、`fetch (` 等写法可绕过）→ 改为脚本按 sha256 固定、样式表解析。
- T261023-142143-2ae3：样式扫描把字符串里的 `/*`、假 `url(` 当真、整表转小写 → 改为词法器。
- T261023-142838-b6bf：`@charset "iso-2022-jp"` + ESC 让浏览器读出 `@import` → 拒绝编码切换；浏览器测试改为真实点击并跨过慢帧阈值。
- T261023-143756-4736：未发现新的绕过，"可以作为发布候选"；建议的浏览器测试加强（等降到最低分辨率后再观察 10 帧）已做。
- 完整测试门：`616700e` 通过（738 秒）。

## 上线（2026-10-23 15:24）

用户授权后 `deploy_realism_release.py --execute` 发布 `2309164`：环境自检通过 → 完整测试门通过 → 220 个文件替换并逐字节回读一致 →
重启后存活、DreamAPI direct 有效且无不确定结果、公网字节与登录门核对通过 → 写入线上记录 `.release-current.json`。
未提交付费任务（付费证据由本规则覆盖）。独立核验：线上 76 个前端文件与 HEAD 一致；桌面与手机黑洞 `ready`，无控制台错误、
无失败请求；手机登录标题已为"欢迎来到 JT / 灵感工作台"两行。截图在工作台 `ui-accretion-2026-10-22/live-2026-10-23-lowpower/`。

## 低功耗黑洞（合并自 `ui/blackhole-low-power`）

- 软件渲染（SwiftShader、llvmpipe 等）直接显示静止黑洞；连续两帧超过 1 秒、或降到最低分辨率仍持续慢帧，也转静止。
- "继续光场"一次点击同时解除暂停和自动静止，本次会话不再自动静止。
- 降分辨率从实际画布像素往下降，手机下限 12 万像素（原先手机第一档 55 万→33 万对 390×844 画布无效）。
- 手机登录页标题 `text-wrap:balance`，"台"不再单独一行。
- 依据：工作台 `ui-accretion-2026-10-22/perf/`、`perf-lowpower/对比.md`：软件渲染下点开面板从最长 4.2 秒降到 0.1 秒以内；
  硬件渲染路径不变，CPU 节流格的差异在改前代码自身复测的波动范围内。真机（低端 Android Chrome、iPhone Safari）尚未验证。
