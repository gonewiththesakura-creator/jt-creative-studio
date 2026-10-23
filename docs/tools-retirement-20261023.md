# 发布路径收拢：删除失效危险脚本、停用按功能发布入口（2026-10-23）

依据工作台 `D:\JT\JT工作台\审计-2026-10-23\发布面盘点\`（Codex 只读盘点 128 个 `tools/` 脚本，Claude 复核后定处置）。

## 为什么

会员上线后面板只监听本机回环，公网 API 需登录。`tools/` 里堆积了 20 多个按功能写的发布脚本和大量 e2e / 压测 / 诊断脚本：
各自挑文件发布、用旧 IP 或匿名 API 核对生产，其中 27 个能提交收费任务，8 个发布脚本**不带任何参数就直接写生产**。
上一次正式发布（09-24）之后功能都是靠它们零散上线的，生产长期落后本地多个提交。现在正式发布器
`tools/deploy_realism_release.py` 已适配会员拓扑并上线了 `c68ddb4`，以后发布只走它。

## 删除（42 个，git 历史可恢复）

条件：没有测试引用、没有其它脚本导入，并且是一次性历史脚本、能提交收费任务、或绕过正式发布器直接写生产/执行任意命令。

```
check_local_index.py check_pub_index.py diag_502.py diag_mem.py diff_local_pages.py
dual_backend_actual_pair.py dump_h3t2v.py e2e_sketch4.py e2e_submit.py extract_anima1_prompts.py
favorites_e2e.py final_preview_smoke.py inspect_hidden_nodes.py inspect_lightx2v63.py
inspect_lightx2v_refs.py original_page_actual_e2e.py public_e2e_video_test.py public_stress2.py
public_stress_batch2.py restart_panel.py rh_realtime_submit_test.py ssh_run.py stress_final3.py
stress_remote_urls.py stress_three_character_modes.py stress_three_styles.py summarize_rh_nodes.py
test_lightx2v_fix.py upload_core_robust.py upload_robust.py upload_server_only.py validate_video_maps.py
validate_video_maps2.py validate_video_maps3.py validate_video_maps_final.py verify_app_shell_live.py
verify_hanmanga_runninghub_real.py verify_local_preview_first_public.py verify_nff_runninghub_real.py
verify_realcomic_public_panel.py verify_realcomic_runninghub_real.py verify_video_render_note.py
```

恢复某个脚本：`git checkout af8fe11 -- tools/<文件名>`（`af8fe11` 是删除前最后一个提交）。
`docs/app-shell-performance.md` 等历史文档里提到的 `verify_app_shell_live.py` 属于这一批。

## 停用（23 个入口，代码保留）

`tools/release_*.py`（19 个）以及 `deploy_liuli_realcomic_release.py`、`deploy_nff_motion_release.py`、`deploy_ui_branch.py`、
`switch_dreamapi_internal.py`：命令行入口统一改为调用 `tools/retired_release.py` 的 `refuse()`，在读取凭据或连接之前退出，
提示改用正式发布器。`main()` 仍可导入，原有离线测试继续覆盖其逻辑；`tests/test_release_scripts_full_gate.py` 锁住入口形状，
并确认模块顶层没有连接或执行命令。要重新启用某个脚本，必须在评审过的提交里改它的入口。

## 保留，暂未处理

- 正式发布器、`prepare_dreamapi_native_canary.py`（canary 及被 18 个脚本导入的连接工具）、构建链、看门狗、`tools/panel_liveness_watchdog.py`。
- 恢复工具 `repair_video_queue_holds.py`、`reconcile_rh_missing_task.py`：会直接改生产任务账本，属于应急手段，保留原样，用前先核对。
- 本地真机测试 `direct_local_dual_smoke.py`、`verify_hanmanga_local_real.py`、`verify_nff_local_real.py`：只占用本机 GPU，不碰生产。
- 盘点标为 `adapt` 的 42 个只读诊断 / 界面核验脚本：多数写死旧 IP 或依赖匿名 API，现在跑不通但不危险；需要时再按会员拓扑改，
  联机验证另行授权。
- 盘点"另发现"里的事项（`favicon.png` 不在正式发布集合、几个旧 SSH 工具用 `AutoAddPolicy`、`inspect_h3_lora_revision.py`
  会把运行凭据取回本机）另行处理。
