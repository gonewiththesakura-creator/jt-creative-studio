# 私有真人化 RunningHub 工作流接入审计

生成日期：2026-09-06

## 范围与证据等级

用户提供了14份JSON（7份ComfyUI编辑格式、7份API格式）、7个`/run/workflow/` ID及7个`/workflow/`编辑页ID。本接入不使用公开作者副本，不在仓库保存RunningHub Key。

最初按消息顺序配对运行ID的假设被真实预校验推翻：Krea2节点227对最初候选ID返回`node_not_found_in_workflow`且无taskId。随后先执行49次单节点探测，再以每套5个分散节点组成多节点结构指纹。每个运行ID均出现唯一的5/5匹配；所有预校验均返回`taskId=""`，没有启动任务或扣费。

## 已机械确认的运行ID映射

| 内部ID | 工作流 | 运行ID | 图片 | 参数 |
|---|---|---:|---:|---:|
| `realism_krea2` | Krea2_动漫转真人 | `2096139245572726785` | 1 | 42 |
| `realism_2511` | 动漫转写实真人2511（零偏移·高还原） | `2096138870382723074` | 2 | 41 |
| `realism_multisample` | 动漫转真人·多采超清天花板 | `2096103615374155777` | 1 | 69 |
| `realism_qwen_zi` | Qwen+ZI动漫转真人写实感洗图 | `2096101840168747010` | 1 | 64 |
| `realism_4k_text` | 超写实4K文生图 | `2095331229284470786` | 0 | 51 |
| `realism_3in1` | 动漫转真人·多分支超清3in1 | `2096094953332416513` | 3 | 105 |
| `realism_zi_flowmatch` | 动漫转真人ZI洗图改（Z-Image+FlowMatch） | `2096150319347859458` | 1 | 58 |

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

## 3in1完整性

当前导出的API可执行图包含：

- 3个`LoadImage.image`图片入口
- 105个允许用户修改的业务字面字段
- 默认提交节点列表共108项

每个面板标签显示节点ID，提示显示节点类型和`fieldName`。编辑图里`mode=4`的旁路实验节点不在API执行图中，因此没有伪装为当前可执行开关。

锁定而不暴露的实现字段：UNET、Checkpoint、CLIP、VAE、LoRA、SAM、检测器、llama.cpp、SeedVR2模型文件、`model/device/device_mode/offload_device`及输出文件前缀。这些是供应商实现路径，不是业务开关。

## 空值语义

ComfyUI的`required`表示调用签名字段存在，并不禁止空字符串。导出默认值为空或仅含空格的字符串使用`allow_blank`：

- 空提示词保持空字符串
- `JoinStrings.delimiter = " "`保持单个空格
- 图片输入仍为业务必传
- 非空关键文本仍执行空值校验

## 已完成验证

- 私有工作流、通用运行时、发布门禁及节点身份：36项通过
- 真实3in1 HTTP合同：3图片+106参数全部进入可信任务
- `false`、整数`0`、合法空文本完整保留
- 浏览器传入的`workflowId`与`nodeInfoList`被丢弃
- 最新隔离Edge浏览器：7/7工作流控件数匹配
- 3in1页面：109个控件
- provider ID不在页面中出现
- 桌面无横向溢出
- 390px手机无横向溢出、触控目标至少44px、当前导航可见
- 全仓库逐文件：46个测试文件中45个通过；唯一红项为基线既有的`test_restore_prompt_contract.py`
- 可恢复真实E2E执行器：5项安全合同通过；已有taskId只查询，提交结果不明确时要求人工核查，绝不自动重提
- Krea2真实E2E：taskId `2096442809591558145`，`RUNNING → SUCCESS`，返回1张有效PNG（8,578,419字节）；视觉检查显示真人化明显、脸部无严重畸形、无文字水印
- 2511真实E2E：taskId `2096445452946796545`，`RUNNING → SUCCESS`
- 多采超清首次默认实例任务 `2096445882042159105` 在节点87 `SeedVR2VideoUpscaler` 因`torch.OutOfMemoryError`失败；RunningHub官方要求48GB任务使用`instanceType=plus`。配置仅为该重工作流启用可信`plus`实例，未降低4096/6000超清默认值
- 多采超清Plus复验：taskId `2096448361467539457`，`RUNNING → SUCCESS`
- Qwen+ZI真实E2E：taskId `2096449521012240385`，`RUNNING → SUCCESS`
- 超写实4K真实E2E：taskId `2096450507881320450`，`RUNNING → SUCCESS`
- 3in1原始109项真实E2E：taskId `2096451072502067201`，`RUNNING → SUCCESS`；安全锁定设备字段后公网schema为108项（3图+105业务参数）
- ZI+FlowMatch真实E2E：taskId `2096452390796980225`，`RUNNING → SUCCESS`；ZIP CRC完整，内含1张有效PNG
- 本地Qwen3-VL质检：8张均完整、构图连贯，无严重脸手畸形。Krea2、2511、Qwen+ZI、4K、ZI+FlowMatch无文字水印；多采和3in1保留输入图原有右侧英文水印，属于源图继承
- 安全加固：持久化幂等请求号、服务重启只恢复既有taskId、视频幂等与并发原子化、HTTP最多2工作线程、ComfyUI输出basename校验、收藏去重及200条上限、回滚manifest/哈希/健康复验
- 最终逐文件回归：46个测试文件中45个通过；唯一红项仍是基线既有`test_restore_prompt_contract.py`
- `/api/workflows`当前未压缩响应229,543字节，本机生成约21ms；API gzip作为非阻断后续优化

## 发布边界

用户明确暂时接受公网免登录。发布仍必须显式提供`--allow-unauthenticated-public`，并在7套真实RunningHub串行E2E、全量回归、Git提交和原子回滚检查全部通过后执行。
