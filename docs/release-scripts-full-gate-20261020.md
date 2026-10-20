# 按功能发布脚本改用全量测试门：2026-10-20

分支 `chore/release-scripts-full-gate`，基于 `70bcdfa`。只改发布脚本和测试，没有改业务代码，没有部署、推送或提交付费任务。

## 改动

自 `70bcdfa` 起，14 个会重启面板的 `tools/release_*.py` 都会发布 `server.py` 的完整模块闭包，但它们原来只跑各自挑选的一部分 pytest（image_loading、access_code_login、security_hardening、h3_lora_slots、video_queue_presets、membership_code、membership_cutover 这 7 个脚本一个测试都不跑）。现在它们统一调用 `deploy_realism_release.run_feature_release_gate(data, normalize)`，在连接生产之前跑完整的 `run_release_tests()`（55 个脚本合同 + 97 个 pytest 文件，Windows 上约 10 分钟）。

| 脚本 | 何时跑全量测试门 |
|---|---|
| 事务族：video_queue_plan、h3_optimized、h3_remix、compact_workflows、image_upload_fix、wardrobe_reference_toggle、image_edit_playback | `--execute` 时，作用域检查之后、连接生产之前 |
| image_loading、access_code_login、security_hardening、h3_lora_slots、membership_cutover | `--execute` 时，连接生产之前 |
| video_queue_presets、membership_code | 每次都跑：这两个脚本没有只读模式，每次运行都会发布 |

- 各脚本自带的 `checks()` / `run_checks()` 已删除。原来额外执行的 `node frontend/verify-contracts.mjs` 由测试门中的 `tests/test_app_shell.py` 覆盖，`tests/test_realism_workbench_contract.py` 属于测试门的脚本合同部分，所以不需要保留额外步骤。compact_workflows 原来按 `backend_changed` 选择测试子集的逻辑也一并删除。
- 不带 `--execute` 的只读预检不跑测试门，仍然很快。
- 已有发布状态文件的检查移到测试门之前，避免先白跑 10 分钟再失败。

## 「Candidate changed during checks」复核

按功能发布脚本发布的是工作树中的候选内容，叠加在生产正在运行的 HEAD 之上，所以测试门测的是工作树，不是干净的提交，也不能像正式发布器那样要求 `require_clean_git()`。复核规则如下：

1. 脚本在测试门之前，按自己的规范化方式（CRLF→LF，webp 等二进制保持原样）读出将要发布的全部字节 `data`。
2. 记录 HEAD 后跑完整的测试门。
3. 测试门通过后，按同样的规范化方式重读这些文件：任何一个字节不同，就报 `Candidate changed during checks: <路径>`；HEAD 变了，就报 `HEAD changed while release tests were running`。两种情况都发生在连接生产之前。
4. 之后的暂存、远端哈希核对和发布后字节核对都使用这份 `data`，所以发布出去的字节，就是测试门开始和结束时磁盘上的字节。membership_cutover 不发布代码，它的预检会重新读取本地文件，与生产哈希比对。

测试门变长后，运行期间误改候选文件的窗口从几十秒变成约 10 分钟。规则保持 fail-closed：发布期间不要在同一检出中编辑；如果报了上述错误，改完后重新运行脚本即可，此时还没有触碰生产。载荷之外的文件（测试、文档）不会发布，所以不复核。如果候选新增了测试文件，需要在同一候选中同步更新 `MIN_PYTEST_FILES` 和 `RELEASE_TEST_INVENTORY_SHA256`，否则测试门会以清单不一致拒绝发布。

## 运行前提

需要用安装了 pytest 和 playwright 的解释器运行，例如 `.venv\Scripts\python.exe tools\release_xxx.py --execute`，并且 `frontend/node_modules` 已就绪（`npm ci`，或用目录联接指向主检出）。

## 测试

新增 `tests/test_release_scripts_full_gate.py`（+1 个 pytest 文件，`MIN_PYTEST_FILES` 96 → 97）：

- 离线运行每个重启型脚本的 `main()`，断言 `--execute` 时先调用测试门、再连接生产，并且交给测试门的 `data` 覆盖闭包、与磁盘字节一致；
- 只读预检不调用测试门；
- 发布脚本里不得再出现 `pytest` 或 `tests/...` 字面量；
- 在临时 git 仓库中验证复核：候选被改、HEAD 移动、测试门失败都会中止，仅换行符不同不会中止。

变异检查：去掉事务中的测试门、把 image_loading 的测试门移到连接之后、让 h3_lora_slots 的只读预检也跑测试门，共有 9 个用例失败。
