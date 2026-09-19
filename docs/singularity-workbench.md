# 黑洞版工作台接入与回滚

设计来源：`D:/JT工作台/ui-competition/blackhole` 的 SINGULARITY 参赛稿。
接入范围：创作台、真人化、视频页。保留既有任务、上传、生图和错误处理脚本；
用独立 CSS / ES module 接入实时黑洞着色器、深色玻璃、金色控件和沉浸观察。
场景属于近似光线弯曲效果，不是完整广义相对论模拟。

## 文件与构建

- `workbench_theme.py`：三个页面构建器共用的挂载函数，只添加皮肤资源和 body 类名。
- `static/singularity/theme.css`：深色工作台样式。
- `static/singularity/workbench.js`：独立视觉控制，无 API 请求、凭据、提示词或任务提交逻辑。
- `static/singularity/shaders.js`：来自黑洞版原型的着色器。
- `static/singularity/vendor`：Three.js 0.186.0，本地分发，MIT 授权见 LICENSE，无 CDN 依赖。

```powershell
python build_unified_three_styles.py
python build_realism_workbench.py
python build_video_workbench.py
python tools/verify_singularity_ui.py
```

手机降低像素预算和帧率，页面隐藏、用户暂停或任务执行时停止连续渲染。
遵循减少动态效果设置。WebGL 或 shader 不可用时保留静态深色背景，业务界面正常可用。
“沉浸”中可拖动观察、滚轮缩放；返回按钮和 Esc 恢复工作台。
场景截图、投放粒子等原型演示按钮没有冒充业务功能加入生成操作。

## Git 回滚

改动前已在远端保存 annotated tag：`rollback/pre-blackhole-20260919`。
基线提交：`294bf689662fec2583a439bcf9f5a841cb8eff07`。
接入分支：`feat/singularity-workbench`。
完成接入的单一提交使用标签 `release/singularity-20260919` 标识。

需要撤销本次皮肤时，在干净工作区执行（若存在后续修改，先检查冲突）：

```powershell
git revert --no-edit release/singularity-20260919
python -u tools/deploy_realism_release.py --execute --allow-unauthenticated-public
```

这会生成撤销提交，保留历史；不要用 `reset --hard`。Git 撤销不会自动修改运行中的网站，
需继续执行发布流程。旧版本页面不引用新资源，遗留资源文件不会影响旧界面。

正式发布器会等待任务安全窗口、创建服务器文件备份、校验资源，并在发布失败时恢复。
服务器事务记录在 `/home/admin/comfy-panel/.release-transactions/`。
本次生图证据复用严格限制为固定资源哈希、固定页面哈希，并证明去掉视觉挂载后所有运行时字节与基线一致；
这不代表重新完成了付费生图测试，后续业务变化仍需对应验证。
