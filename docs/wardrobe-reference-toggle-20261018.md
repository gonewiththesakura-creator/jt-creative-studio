# 换装图二参考图开关

`qwen21_wardrobe` 默认开启「使用图二参考图」，保持原先双图行为。关闭时收起图二上传区，只要求人物图和换装提示词；本地已选图二保留，重新开启无需再次上传。提交、排队编辑、重做、收藏参数中的 `use_clothing` 均由可信布尔 schema 处理；旧任务没有该字段时仍采用双图模式。

后端关闭模式忽略图二上传 token，且不向上游传图二。服务端保存经过核验的单图 API 执行图：移除节点 475 和 `484.inputs["images.image_2"]`，保留原模型、采样、人物图连接，动态填入人物图、提示词和采样参数。单图分支通过高级工作流接口的 `workflow` 字符串提交，双图仍使用既有接口。浏览器无法提交自定义执行图，公开目录不返回私有图或模型路径。

高级提交无自动重试，避免网络丢失回执导致重复计费；任务 ID、状态查询、用户隔离和额度沿用原队列机制。

核对依据：

- [节点文档：参考图可选，支持 0–16 张](https://github.com/Comfy-Org/docs/blob/main/built-in-nodes/TextEncodeQwenImage21.mdx)。
- [高级工作流接口：支持完整 API 格式 workflow JSON 字符串](https://rhtv.runninghub.cn/runninghub-api-doc-cn/api-425749013)。
- 发布使用 `tools/release_wardrobe_reference_toggle.py` 的既有锁、排空、服务器本地备份、逐字节交换、数据核对和回滚事务。只替换图片编辑资产、可信配置与服务端代码。
- `tests/test_wardrobe_reference_toggle.py` 覆盖单双图的必传校验、关闭后忽略过期图二、重做保留开关、实际提交图无图二、拒绝浏览器注入图、丢失回执不重试、旧任务默认分支。
- `tests/test_image_edit_browser.py` 覆盖 390/1440 宽度的开关、上传/粘贴、收起、重新开启保留图片、单/双图提交与重做。
- 线上检查脚本 `tools/verify_wardrobe_reference_toggle_live.py` 只检查真实登录后的公开目录、桌面/手机开关和上传区显示，不上传或提交生成。

未做实际收费生成，不能将界面和提交格式测试视为上游生成质量验收。发布及线上结果保存于 `audit/wardrobe-reference-toggle-20261018/`。

本次结果：221 项回归通过，页面契约与打包检查通过。发布事务 `committed` 且 `cleanup_complete=true`，1057 条既有任务在重启前后完全一致。线上已验证手机和桌面开关、图二上传区收起/恢复、私有执行图不暴露，业务写入 0、页面错误 0，检查会话已退出。
