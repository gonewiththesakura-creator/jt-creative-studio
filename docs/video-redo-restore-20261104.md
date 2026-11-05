# 视频重做恢复表单（2026-11-04）

任务卡的“重做一次”和 ↻ 仅 GET `/api/video-redo-draft?job_id=…`，
恢复工作流、提示词、负面提示词、LoRA、时长、尺寸、种子和素材状态。
用户修改后点击生成，走普通 `/api/video-generate`，不带 `redo_job_id`。
旧服务端 redo 路径继续兼容。

草稿接口要求登录且 `session_owns_record` 校验通过，非所有者返回 404，
运行中或待核对任务返回 409；响应禁止缓存，不公开 provider_media 路径。
接口不改任务、不入队、不访问上游；唯一持久化副作用是签发上传 capability。

上传 capability 的 TTL 为 24 小时，普通提交不消费 token，可在到期前复用。
但任务只存原文件名和 provider_media，注册表只存 token 哈希，无法还原原 token。
因此接口为当前所有者会话重签同一 provider 引用，绑定原工作流、输入槽、素材类型，
到期时间不超过原 `queue_media_expires`（旧任务回退 created + 24 小时）。
过期或缺少可用引用的槽位返回 valid=false、token=null，提示重新上传。
这里的“有效”依据本地 capability 合同及到期时间，不探测上游文件是否被提前移除。
可用缩略图沿用受所有权保护的 `/api/video-thumbnail/…`。

种子恢复任务保存的数值，不额外随机化；显式随机哨兵值也按保存值恢复。
恢复成功清除旧的普通提交待确认请求号，使后续生成成为新的普通提交。

后端离线 HTTP 测试覆盖所有权、过期、内部路径隔离、重签 token 普通提交及原任务不变；
真实 Chromium 测试覆盖三种终态与有效/过期素材、两个入口不提交、修改后普通提交。
构建顺序为 `build_video_workbench.py`、`tools/build_frontend.py`。

发布门采用独立 `reviewed_video_redo_restore_patch` 固定实现提交的运行时和前端哈希，
其余运行时文件与原实证逐字节比较。这是离线审查放行，非新的付费视频实证。
