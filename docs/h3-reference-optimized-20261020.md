# MiniMax H3 多参考生视频（优化版）接入

## 来源与范围

- 工作台 ID：`h3_reference_optimized`；入口为“视频 → MiniMax H3 → 多参考生视频（优化版）”。
- 用户指定的执行 ID：`2111727257252290561`；编辑器 ID：`2112090338620891138`。执行 ID 与编辑器 ID 分开保存，提交仅使用执行 ID。
- 用户原始导出 SHA-256：`2912961c834da66ae1da6c50919324e15a6ccc734bca9a3cec107928d2132edd`。
- 只读获取的可执行图 SHA-256：`5182d336c7bb2d12fe259400f01f43de617d5a2303625149d3ea514716546e83`。
- 导入脚本逐项核对有效节点及连线，解析编辑器 Set/Get/Reroute，恢复原导出中被旁路的二采和动作 LoRA 节点。没有修改其他工作流定义。

## 行为

最多 9 张参考图、3 段视频、3 段音频，混合总数最多 12，至少需要图片或视频。使用现有紧凑上传布局、分类计数、逐个出现的上传位、Ctrl+V、替换与红点删除。提示词可以用 `<Picture 1>`、`<Video 1>`、`<Audio 1>` 引用对应类型中的素材顺序。

共 32 项参数，包括提示词、时长、比例、分辨率、种子、采样步数、去噪强度、参考图处理方式、显存优化、三组 LoRA 开关与权重、视频截帧和音轨参考、输出压缩和往返播放。高级参数折叠；开关沿用按钮样式。

保留原文件的默认行为：总步数 12、一采 8、二采放大默认关闭，放大倍数 1.5；开启二采后继续使用剩余采样区间。固定输出 24 fps，原来的帧数对齐表达式保留。只有第一段参考视频参与自动时长识别，后续参考视频不会覆盖已设置的输出时长。

按选中输出遍历依赖：未上传的媒体、未启用的 LoRA、未使用的二采支路不会进入提交图。删除作者示例素材引用，使用中性示例提示词。随机种子按任务标识派生，避免不确定的提交重试改变种子。保留既有账户隔离、上传凭证、套餐限制、排队、取消、重做、历史与收藏链路。前端不接收模型路径、内部图或执行 ID。

## 验证边界

- 发布前 185 项测试通过，覆盖图连线、条件支路、媒体限制、参数校验、凭证归属、CSRF、队列幂等、失败重做以及 390px/1440px 浏览器操作；打包校验确认 232 个业务函数在打包时没有改变。
- 真实部署及上传结果记录在 `audit/h3-optimized-20261020/release.json` 和 `live-verification.json`。测试使用小型纯色图、短视频、静音音频，脚本拦截所有生成请求。
- 本次线上结果：发布状态 `committed`、清理完成；1,076 条任务及全部既有会员、套餐、收藏和上传凭证数据保留。图片 Ctrl+V、视频、音频上传均成功，接口均返回 200；32 项公开参数及密钥隔离检查通过，390px 布局无横向溢出，测试会话已退出。
- 未执行真实收费生成；测试通过不代表云端 GPU 节点已完成实际出片验收。
- 发布使用既有事务，服务器本地备份，核对全部既有账本、收藏、上传凭证和会员数据；禁止用本机数据覆盖线上。

## 维护

- 导入：`tools/import_h3_optimized.py`；私有节点拼装：`server.py` 的 `rh_build_h3_optimized_graph`。
- 表单：`sources/h3_remix_controls.js` 与 `sources/video_business.js`；重新运行 `build_video_workbench.py`、`build_realism_workbench.py`、`tools/build_frontend.py` 生成打包资产。
- 发布：`tools/release_h3_optimized.py` 默认只读，`--execute` 使用数据保全事务。必须在发布后提交 Git，避免发布基线失配。
- 在线验证：`tools/verify_h3_optimized_live.py`，仅保留无密钥的测试摘要，结束时退出测试会话。

原生节点对照：[多参考节点说明](https://github.com/Comfy-Org/docs/blob/main/built-in-nodes/MiniMaxH3ReferenceToVideo.mdx)、[分辨率节点源码](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_resolution.py)。原始导出和只读 API 图才是本次接入的具体依据。
