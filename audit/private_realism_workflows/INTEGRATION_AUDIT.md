# 私有真人化 RunningHub 工作流接入审计

生成日期：2026-09-06

## 范围与证据等级

用户提供了14份JSON（7份ComfyUI编辑格式、7份API格式）、7个`/run/workflow/` ID及7个`/workflow/`编辑页ID。本接入不使用公开作者副本，不在仓库保存RunningHub Key。

最初按消息顺序配对运行ID的假设被真实预校验推翻：Krea2节点227对最初候选ID返回`node_not_found_in_workflow`且无taskId。随后先执行49次单节点探测，再以每套5个分散节点组成多节点结构指纹。每个运行ID均出现唯一的5/5匹配；所有预校验均返回`taskId=""`，没有启动任务或扣费。

## 已机械确认的运行ID映射

| 内部ID | 工作流 | 运行ID | 图片 | 参数 |
|---|---|---:|---:|---:|
| `realism_krea2` | Krea2_动漫转真人 | `2096139245572726785` | 1 | 4 |
| `realism_2511` | 动漫转写实真人2511（零偏移·高还原） | `2096138870382723074` | 1 | 3 |
| `realism_multisample` | 动漫转真人·多采超清天花板 | `2096103615374155777` | 1 | 4 |
| `realism_qwen_zi` | Qwen+ZI动漫转真人写实感洗图 | `2096101840168747010` | 1 | 5 |
| `realism_4k_text` | 超写实4K文生图 | `2095331229284470786` | 0 | 9 |
| `realism_3in1` | 动漫转真人·多分支超清3in1 | `2096094953332416513` | 1 | 4 |
| `realism_zi_flowmatch` | 动漫转真人ZI洗图改（Z-Image+FlowMatch） | `2096150319347859458` | 1 | 3 |

用户还提供了以下编辑页ID集合：

`2096429284419297282`、`2096429253886091265`、`2096429217290788865`、`2096429184066584577`、`2096429156329652225`、`2096429130804240386`、`2096429100839010305`。

由于编辑页登录令牌过期、导出JSON不嵌入workflowId，目前不把这些编辑页ID强行一一绑定到文件；它们只作为用户提供的来源集合保留。生产运行不依赖编辑页ID。

## Schema提取

通过RunningHub只读ComfyUI兼容`object_info`获得当前节点定义：

- RunningHub节点类总数：18,158
- 本批API图使用的节点类：89
- 匹配：89/89
- 缺失：0

机械获得类型、枚举、默认值、最小值、最大值、步长、多行文本及布尔定义。可重复导入器为`tools/import_private_realism_workflows.py`；修改配置前会校验全部14份源文件SHA-256。

## 3in1源图与精简产品Schema

当前导出的API源图包含3个`LoadImage.image`与105个可覆盖字面字段，原始109项完整payload已经真实E2E成功。按用户产品意图，面板不再把这些技术参数全部公开，而采用明确业务白名单：

- 当前可执行“漫画转真人”分支：1张真正进入最终结果链的动漫原图
- 转换要求、主Seed、输入最长边
- “成人向细节增强”逻辑开关：由服务端可信映射同时控制节点1304 LoRA强度与节点1399配套提示词
- Z-Image质感、面部修复、SeedVR2放大在当前API拓扑中固定串联，界面如实显示“固定启用”，不伪造成开关
- 图像编辑与局部换装在编辑图中为`mode=4`，API导出已删除处理链；界面显示为暂不可用，取得各自RunningHub运行ID前不提供假开关

浏览器仅看到业务标签、类型、默认值、选项和范围，不再下发节点ID、`fieldName`、节点类型或可信覆盖映射。

锁定而不暴露的实现字段：UNET、Checkpoint、CLIP、VAE、LoRA、SAM、检测器、llama.cpp、SeedVR2模型文件、`model/device/device_mode/offload_device`及输出文件前缀。这些是供应商实现路径，不是业务开关。

## 空值语义

ComfyUI的`required`表示调用签名字段存在，并不禁止空字符串。导出默认值为空或仅含空格的字符串使用`allow_blank`：

- 空提示词保持空字符串
- `JoinStrings.delimiter = " "`保持单个空格
- 图片输入仍为业务必传
- 非空关键文本仍执行空值校验

## 已完成验证

- 私有工作流、通用运行时、发布门禁及节点身份：36项通过
- 原始3in1完整payload真实E2E已留档；精简后HTTP合同验证1图+4参数及逻辑开关可信展开
- `false`、整数`0`、合法空文本完整保留
- 浏览器传入的`workflowId`与`nodeInfoList`被丢弃
- 最新隔离Edge浏览器：8个统一真人化方案控件数逐项匹配
- 7套Workflow共7个图片字段、33个参数字段；快速AI App另有1图+1要求
- 3in1页面：5个业务控件（1图+4参数）
- provider ID不在页面中出现
- 桌面无横向溢出
- 390px手机无横向溢出、触控目标至少44px、当前导航可见
- 全仓库逐文件：48个测试文件中47个通过；唯一红项为基线既有的`test_restore_prompt_contract.py`
- 可恢复真实E2E执行器：5项安全合同通过；已有taskId只查询，提交结果不明确时要求人工核查，绝不自动重提
- Krea2真实E2E：taskId `2096442809591558145`，`RUNNING → SUCCESS`，返回1张有效PNG（8,578,419字节）；视觉检查显示真人化明显、脸部无严重畸形、无文字水印
- 2511真实E2E：taskId `2096445452946796545`，`RUNNING → SUCCESS`
- 多采超清首次默认实例任务 `2096445882042159105` 在节点87 `SeedVR2VideoUpscaler` 因`torch.OutOfMemoryError`失败；RunningHub官方要求48GB任务使用`instanceType=plus`。配置仅为该重工作流启用可信`plus`实例，未降低4096/6000超清默认值
- 多采超清Plus复验：taskId `2096448361467539457`，`RUNNING → SUCCESS`
- Qwen+ZI真实E2E：taskId `2096449521012240385`，`RUNNING → SUCCESS`
- 超写实4K真实E2E：taskId `2096450507881320450`，`RUNNING → SUCCESS`
- 3in1原始109项真实E2E：taskId `2096451072502067201`，`RUNNING → SUCCESS`；安全锁定设备字段后公网schema为108项（3图+105业务参数）
- 3in1精简关闭态真实E2E：taskId `2096768750299181057`，1图+4参数，`local_detail_lora=false`由服务端展开2项可信覆盖；SUCCESS，耗时316秒，返回节点1708/1709/1707/1706共4张结果
- ZI+FlowMatch真实E2E：taskId `2096452390796980225`，`RUNNING → SUCCESS`；ZIP CRC完整，内含1张有效PNG
- 本地Qwen3-VL质检：8张均完整、构图连贯，无严重脸手畸形。Krea2、2511、Qwen+ZI、4K、ZI+FlowMatch无文字水印；多采和3in1保留输入图原有右侧英文水印，属于源图继承
- 安全加固：持久化幂等请求号、服务重启只恢复既有taskId、视频幂等与并发原子化、HTTP最多2工作线程、ComfyUI输出basename校验、收藏去重及200条上限、回滚manifest/哈希/健康复验
- 最终逐文件回归：48个测试文件中47个通过；唯一红项仍是基线既有`test_restore_prompt_contract.py`
- 一级导航已合并为“真人化”；旧`/realcomic`以302跳转到`/realism?workflow=realcomic`，旧任务和收藏兼容迁入统一页面

## 发布边界

用户明确暂时接受公网免登录。发布仍必须显式提供`--allow-unauthenticated-public`，并在7套真实RunningHub串行E2E、全量回归、Git提交和原子回滚检查全部通过后执行。
