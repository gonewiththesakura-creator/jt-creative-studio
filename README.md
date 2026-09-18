# JT 灵感工作台

## GitHub 同步快照（2026-09-18）

- 私有仓库：<https://github.com/gonewiththesakura-creator/jt-creative-studio>。
- 当前开发分支：`feat/four-realism-workflows-cold-style`。
- 最近已部署代码：`40bf6f1bf54dd4f359cc16070e4eaf7e7e6da820`；部署核验见 `audit/dreamapi_native_20260918/error-localization-deployment.json`。
- 已取消网站自行添加的 API / 云端生图小时与每日次数限制，保留并发保护、重复提交防护和任务恢复；常见失败原因已中文化。
- 最新部署回归记录为 55 个检查脚本、506 项 pytest 测试通过。这不代表中转站实时可用。
- 尚未修复：转发程序返回字符串形式的 `error` 时，后端可能丢失具体原因，把本地 429 误显示为上游限流；近期还出现连接中断。不要把已通过部署检查等同于这些问题已解决。
- 本仓库不包含 API Key、SSH 私钥、服务器登录凭据、运行任务账本及用户上传媒体；部署时需单独配置。

下方 2026-09-15 快照与交接文档保留作历史参考；涉及版本、远程仓库和发布状态时，以上述更新及当前代码为准。GitHub 同步不会自动部署生产网站。

这是项目的统一入口。当前完整交接、生产状态、架构、工作流、测试、发布、排障、安全边界和未完成事项，统一以 [`项目交接-2026-09-15.md`](项目交接-2026-09-15.md) 为准。

## 当前快照

| 项目 | 当前值 |
|---|---|
| 本地目录 | `D:\LAN-Share\lora\_work\comfy_panel` |
| 分支 | `feat/four-realism-workflows-cold-style` |
| 运行版本 | `e6067916d62f02ece22e8e42fca2d66cc6101d00` |
| 生产入口 | <http://8.210.125.65:8189> |
| 生产目录 | `/home/admin/comfy-panel` |
| 产品规模 | 4 个主要页面、10 种创作画风、21 个工作流 |
| Git remote | 未配置 |

2026-09-15 只读核对时，生产服务、工作站代理、双隧道和三个任务槽均正常；41 个正式发布文件与本地 `e606791` 逐字节一致。该健康检查不探测 DreamAPI 上游凭据是否仍有效，也不代表上游此刻一定能出图。

## 接手先看

1. 阅读 [`项目交接-2026-09-15.md`](项目交接-2026-09-15.md)。
2. 不要把旧文档中的“当前状态”当成现状。
3. 不要立即执行正式发布：当前 DreamAPI 真实 E2E 证据仍固定在 `f7c1798`，发布门会因 `e606791` 的运行载荷变化而失败关闭。
4. 不要读取、打印或提交 `tools/creds.json`、`tools/id_ed25519`、`PANEL_TOKEN.txt`、`.env*` 或 `panel_data/`。
5. 已取得供应商任务号的收费请求不得自动重提。

只读检查：

```powershell
git status --short --branch
git log -5 --oneline
curl.exe -fsS --max-time 15 http://8.210.125.65:8189/api/health
python -c "import tools.deploy_realism_release as d; print(d.validate_dreamapi_migration_e2e_manifest())"
```

## 判定优先级

1. 当前代码、配置和实时运行状态：行为事实。
2. `项目交接-2026-09-15.md`：当前唯一完整交接。
3. 当前测试与冻结审计清单：验证事实及其边界。
4. `项目交接-2026-09-13.md`、`项目审查-2026-09-13.md`：历史审查与修复记录。
5. `运维文档_远程控制面板.md`、`冷脸萌提示词生成器_RunningHubAPI_项目交接_2026-08-25.md`，以及后者配套的 `.docx/.spec.json`：早期历史资料。

## 权威入口

- 后端：`server.py`
- 工作流目录：`config.json`
- Windows 守护与双隧道：`comfy_watchdog.py`、`tools/start_comfy_watchdog.ps1`
- Linux 存活守护：`tools/panel_liveness_watchdog.py`、`deploy/comfy-panel-watchdog.service`、`deploy/comfy-panel-watchdog.timer`
- 预览资产构建器：`tools/build_preview_assets.py`
- 创作台构建器：`build_unified_three_styles.py`
- 真人化构建器：`build_realism_workbench.py`
- 视频构建器：`build_video_workbench.py`、`sources/video_business.js`
- 正式发布器：`tools/deploy_realism_release.py`
- 测试：`tests/`
- 冻结证据：`audit/`

生成页必须从构建源重建，禁止只手改 `static/*.html`。旧 `tools/deploy.py` 等入口已退休，正式发布只能使用交接文档指定的发布器。
