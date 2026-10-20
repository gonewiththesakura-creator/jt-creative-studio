# 全量回归门恢复与失败分类：2026-10-19

分支 `chore/green-test-gate`，基于 `7f10ec5`。本次只改测试、测试脚手架和发布器的测试门本身，没有改业务代码，没有部署或提交付费任务。

## 结论

- `tools/deploy_realism_release.py` 的 `run_release_tests()` 在本地 Windows 全绿（55 个脚本合同 + 93 个 pytest 文件）。
- 测试清单基线已更新为当前清单：`MIN_PYTEST_FILES` 40 → 93，`RELEASE_TEST_INVENTORY_SHA256` 改为 `c064ff26…496e`。
- 真实回归和需要用户决定的项目都没有在业务代码里修复。它们在测试里用 `xfail(strict=True)`、精确固定的已知漂移或尺寸上限锁住：问题修好或决定落地后，测试会转红，提醒删除这项例外。

## 脚手架修复

| 改动 | 原因 |
|---|---|
| `run_release_tests()` 给子进程设置 `PYTHONPATH=<repo>` 和 `PYTHONIOENCODING=utf-8`，读取输出时按 UTF-8 解码 | 21 个脚本合同用 `spec_from_file_location` 加载 `server.py` 后，导入同级模块时报 `ModuleNotFoundError: video_uploads / membership_media` |
| pytest 改用私有 `--basetemp` 和 `-p no:cacheprovider`，超时从 1200 秒调整为 1800 秒 | Windows 共享 `pytest-of-<user>` 目录会出现 PermissionError；全量运行约需 10 分钟 |
| 新增 `tests/conftest.py`，把仓库根目录加入 `sys.path` | 直接运行 pytest 时与发布门行为一致；`conftest.py` 不计入清单 |
| AST 计数门改为按路由覆盖：`route_guarded_calls` / `route_coverage_errors` | 原来要求 `reserve_upload_attempt` 恰好调用 4 次，现为 5 次，新增调用来自 `/api/upload` 的 octet-stream 分支。现在每条公开上传路由（`/api/workflow-upload`、`/api/realcomic-upload`、`/api/upload-start`、`/api/upload`，以及任何新发现的 `*upload*` 路由）都必须调用。`register_billable_job` 也改为同样的语义，覆盖 5 条 `*generate` 路由。删掉任何一处调用仍会使测试失败 |
| `.gitattributes` 固定 `audit/dreamapi_direct_final_20260918/verification.json` 为 `eol=lf` | 在 autocrlf 检出中，这份按字节哈希固定的证据会被转成 CRLF，哈希随之对不上。仓库对其他证据文件已有同样处理 |
| `test_preview_loading_performance` 改为按 LF 字节计算页面大小 | 线上部署的是 LF 字节，Windows 的 CRLF 检出曾让页面额外多出约 400 字节 |

本地共完整运行两次。第一次有 2 个失败：`test_video_queue::test_slots_refill…` 在 `os.replace` 处报 Windows `PermissionError [WinError 5]`，`test_direct_uploads::test_direct_http_registration…` 也失败了，但它的详情被发布器只保留最后 4000 字符的输出截掉了，没能确认失败原因。这两个文件单独连续跑 3 次都通过，第二次全量运行全部通过（534 秒）。目前推测是 Windows 下的偶发问题：目标文件仍被其他句柄打开时，`os.replace` 会失败。生产环境是 Linux，所以没有修改业务代码，但如果今后在 Windows 上反复出现，需要再查。

环境前提（未提交）：`tests/test_app_shell.py` 需要 `frontend/node_modules`（acorn）。新工作树需先在 `frontend/` 下执行 `npm ci`。本次用目录联接指向主检出已安装的依赖。

## 分类清单

### A. 测试过期（已更新测试，并引用对应提交）

| 测试 | 依据 |
|---|---|
| test_collapsed_defaults_contract / test_compact_two_step_drawers / test_original_two_step_workbench_contract | `fed8f64`：分类抽屉改为互斥展开 |
| test_navigation_performance_contract（媒体缓存） | `0f7d493`：public 改为 private；`97be240`：私有图片改为 no-store；`4aa41f6`：视频改为 `private, max-age=3600` |
| test_navigation_performance_contract（路由预取） | `4aa41f6`：/realism 重建为图片编辑页；`db36eeb`：应用外壳的 router 在 pointerenter 时预加载导航 |
| test_navigation_performance_contract（lazy） | `15f4c40`：结果图改由 gallery_image_loader 显式加载，仍为 async decode |
| test_realcomic_ai_app_contract | `4aa41f6`：ai_app 改走 `/api/image-edit-generate`（服务端 `allowed_kinds` 含 ai_app）；历史请求改用 URLSearchParams |
| test_realism_visual_hierarchy_contract | `4aa41f6`：图片编辑复用视频任务卡操作；`db36eeb`：外壳导航在手机上整行居中，不再横向滚动 |
| test_ui_polish_unified_contract、test_unified_realism_navigation | `4aa41f6`：导航「真人化」改名为「图片编辑」 |
| test_app_shell | 环境问题：缺少 `frontend/node_modules`，不是代码问题 |
| test_client_secret_retirement（2 项） | `a28b141`：管理入口常驻可见，验证在对话框内完成，回跳带 `?admin=plans` |
| test_dreamapi_creator_ui（2 项） | `15f4c40`：结果画廊代码迁到 `sources/gallery_image_loader.js`，由构建器内联 |
| test_private_realism_workflows | `1133c7d`：只从 speed 文案中去掉了提供方名称（已核对其余字段无差异），接受基线随之前移 |
| test_realism_deploy_contract（lazy assets、发布清单） | `4aa41f6`：图片编辑接口变更；`a221347` / `939cd2c` / `547e6cc`：server.py 运行时依赖加入发布清单 |
| test_security_server_boundaries | `4aa41f6`：私有视频改为 `private, max-age=3600`，并带 `Vary: Cookie` |
| test_server_review_regressions（旧 cookie） | `8c9a122`：迁移窗口截至 2026-10-15 UTC，测试过期是时钟导致。现在分别验证截止后拒绝、窗口内接受 |
| test_uploaded_workflow_catalog | `4a46084`：新增参考图 2–4；`547e6cc`：服务端绑定的 LoRA 槽位 |
| test_watchdog_and_video_bounds（h3_remix_full） | `e611c4c`：int 控件未写 step 时，浏览器默认 step 为 1，测试按 1 处理 |
| test_frontend_workbench_regressions | `eb3cf6b`：占位核对文案改写 |
| test_video_catalog_sections_and_results | `fd03485`：文件结果并入媒体画廊 |
| test_video_library_browser | 时序问题：页面网络请求结束前就 hover，画廊重渲染导致 hover 对象失效，改为等待 networkidle |
| test_video_library_controls、test_video_upload_client_runtime（2 项） | `97be240`：上传凭据留在服务端，改走 upload-start/chunk/finish 分块接口，失败文案改为「上传暂未完成」 |
| test_video_upload_client_runtime（2 项 harness） | `38884c4`：新增顶层画廊监听；`547e6cc`：LoRA 设置拆为独立源文件，harness 按构建器顺序拼接 |
| test_workbench_glass_layout（10 个 error） | `4aa41f6`：构建器依赖 `workbench_task_runtime.py` 等，夹具改为复制完整 sources；两页共用 addTaskCard |
| test_uploaded_workflow_release_gate（配额） | 本次的路由覆盖语义 |

### B. 真实回归（未改业务代码，交给用户决定）

| 项 | 代码位置 | 测试中的处理 |
|---|---|---|
| ~~同账号会话过期后重新登录会整页重载，未提交的表单草稿丢失~~ **2026-10-20 已修复**：只有换了账号才整页刷新；同一账号重新登录时不刷新，并发出 `jt:media-restore`，图片加载器只按记下的地址重新拉取过期时清掉的私有图片，过期期间不保留图片内容 | `frontend/account.js`、`sources/gallery_image_loader.js` | 去掉 strict xfail；新增 `test_same_account_restore_refetches_cleared_images_in_place` |
| ~~正式发布清单缺少 server.py 导入的 `membership_http.py`、`membership_store.py`、`membership_media.py`、`result_image_cache.py`；按正式发布器发布时，这些模块不会随 server.py 一起更新~~ **2026-10-20 已修复**：`server_runtime_module_paths()` 从 server.py 起按 import 传递推导模块清单，另补上之前漏查的间接依赖 `membership_auth.py` | `tools/deploy_realism_release.py` 中的 `SERVER_RUNTIME_MODULE_PATHS` / `RELEASE_RELATIVE_PATHS` | 去掉 xfail；测试独立计算闭包并比对，另加懒加载、传递依赖、相对导入与本地包 fail-closed 的用例 |

### C. 需要用户决定

| 项 | 说明 | 测试中的处理 |
|---|---|---|
| ~~h3_edit_n 的 duration 没有上限~~ **2026-10-20 已决定**：用户把上限定为 25 秒 | `config.json` 中 duration 为 `min 4 / max 25`；服务端拒绝超过上限的值，视频页自动识别源视频时长时也会夹到 25 秒 | 豁免和 strict xfail 已删除，边界用例覆盖 26 秒被拒绝 |
| h3_edit_n 公开 schema 与发布门评审版本不一致（参考图 2–4、LoRA） | **2026-10-20**：时长有了上限，`UPLOADED_WORKFLOW_FIELDS` 和 `UPLOADED_WORKFLOW_CONTROL_SCHEMA_SHA256` 已按当前结构重新固定。2026-09-12 的线上 schema 证据早于这些映射，刷新需要用生产账号向 RunningHub 只读拉一次 schema，需用户授权 | 只剩 `uploaded workflow live mappings invalid: h3_edit_n` 这 1 条漂移被精确固定 |
| ~~创作页 `promptgen.html` 超出快速启动预算~~ **2026-10-20 已决定**：独立页预算放宽到 452,000 LF 字节。实测这个页面只在 `/promptgen` 使用，约 80% 是内嵌的 base64 预览图；用户访问 `/` 走 App Shell，创作页路由首次加载 gzip 后约 29.7KB。这次重建（重登修复加导航标签）后，独立页为 450,798 字节，App Shell 创作页首次下载（含 app.html、main、账号模块）gzip 增加 307 字节 | — | 去掉 ratchet；新增 App Shell 创作页路由 gzip 预算 32,000 字节 |
| 原生 DreamAPI 付费证据与当前运行时不一致 | 运行时自 `f7c1798` 起已变化。刷新证据需要用户授权一次付费 canary，本次没有提交 | `test_app_shell_has_reviewed_paid_evidence` 标为 strict xfail。正式发布的 preflight 仍会因此拒绝发布 |
| ~~promptgen.html 的导航仍显示「真人化」~~ **2026-10-20 已同步** | 2026-10-20 重建后，所有页面导航都显示「图片编辑」 | 测试改为只接受「图片编辑」 |
