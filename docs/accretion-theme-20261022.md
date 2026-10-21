# 吸积 ACCRETION 主题落地（2026-10-22）

分支 `ui/accretion-theme`，基于 `ui/mobile-sticky-generate`（`7cf531c`）。只改皮肤层、外壳和黑洞联动，
不改业务脚本、接口、`config.json` 或后端；`frontend/verify-contracts.mjs` 确认打包后 232 个业务函数体不变。
**未部署、未推送、未提交任何付费任务。**

设计来源：工作台 `D:\JT\JT工作台\ui-redesign-2026-10-20\accretion\` 原型和同目录 `审查报告.md`。
原型只做了文生图；这里按原型 README 的"复用现有单 Renderer 和忙状态通道"路线，把它的设计令牌、
层级规则和黑洞行为套到现有三个页面的全部功能上，没有把参数表单塞进一条输入坞。

## 改了什么

| 文件 | 内容 |
|---|---|
| `static/singularity/theme.css` | 重写为吸积设计令牌：纯黑底，白热→琥珀→余烬；字号只用 12/13/15/20/28；分组用细线不再框套框；火焰实色只给生成按钮，选中态琥珀描边，禁用态空心；图标改 SVG 遮罩；结果图悬浮在视界前、原样显示不裁切（缩略图保持 contain）；任务卡状态用颜色和光晕。旧变量（`--brand`、`--border` 等）映射到新色板，构建器页面自动跟随 |
| `static/singularity/workbench.js` | 任务进行时**不再暂停**黑洞：`energy` 以 1.6/s 趋向 1，盘面时间 ×(1+2.4·energy)、亮度和色温上升；任务结束时光子环闪一次（`ringPulse`）。忙状态新增图片编辑/视频的运行中任务卡；页面根节点加 `accretion-busy` 类，生成坞顶边有一道扫光 |
| `static/singularity/shaders.js` | 吸积盘色带改为余烬→琥珀→金→白热；新增 `ringPulse` 统一变量 |
| `static/singularity/appearance.js` | 玻璃色改为暖黑；默认值：色温 .62、曝光 .8、光晕 .1、面板 .74、输入区 .55、顶栏 .62、边缘 .15。已保存过外观的用户保留自己的值 |
| `tools/build_frontend.py` | 新增 `page_theme()`：页面样式里的皮肤副本去掉 `/* shell-only:start */…/* shell-only:end */` 段和注释。顶栏、场景菜单、画布、外观控制台和图标变量只在外壳文档里，页面在 ShadowRoot 里碰不到，图标变量从外壳 body 继承。创作台首屏 gzip 因此从 35,177 回到 31,470（预算 32,000） |
| `frontend/index.html` | 品牌统一为"JT 灵感工作台"；收藏/历史去掉 Unicode 图标，文字包在 `<span>` 里（手机只显示图标） |
| `frontend/styles/app.css` | 去掉手机顶栏的 `!important` 覆盖（皮肤改为两行网格，保留合同要求的 `.topnav{order:3;width:100%;justify-content:center}`）；登录卡、账号弹窗、管理后台换成同一套令牌 |
| `frontend/styles/page.css` | 外壳内去掉页面 `.app-shell` 的 `z-index:1` 和页面根的 `isolation`，收藏/历史抽屉不再被外壳顶栏压住（手机上关闭按钮原来点不到） |
| `frontend/account.js` | 登录页标题改为"欢迎来到 JT 灵感工作台" |
| `tests/test_login_scene.py` | 外观玻璃色断言从 `rgba(15,16,20,…)` 改为 `rgba(16,12,10,…)` |
| `tests/test_video_library_browser.py` | `mouse.wheel` 不等滚动生效就返回，原测试紧接着读 `scrollTop` 是竞态；从 `7cf531c` 起稳定失败（`ffa47a4` 通过）。改为等待 `scrollTop>0`，页面行为没变 |
| `tools/verify_app_shell.py` | 场景按钮已收进"场景"菜单；忙状态断言从"模拟时间不变"改为"模拟时间继续前进" |

三个构建器重跑后，旧页面只有皮肤 `?v=` 哈希变化。

## 验证

- `node frontend/verify-contracts.mjs`：232 个业务函数体不变。
- 与界面相关的 7 个浏览器测试文件（App Shell、玻璃布局、登录场景、API 浮层、管理入口、激活码、会员）82 项全过。
- 完整发布测试门：见提交说明。
- 离线截图（真实 WebGL，所有接口为假数据，非 GET 一律拒绝）：工作台 `ui-accretion-2026-10-22/shots/`，
  桌面 1440×900 与手机 390×844，覆盖空闲、生成中、出图、图片编辑、视频、场景菜单、历史、账号、登录页。
  任务进行中盘面速度为空闲时的 3.36～3.41 倍，结束后回到 1.0 倍；无控制台错误，无横向溢出，可见文字均不小于 12px。
- 没做：实体手机 GPU、长时间功耗、Safari/Firefox、线上真实任务。

## 过程中发现并修掉的

- 手机上收藏/历史抽屉的关闭按钮被外壳顶栏盖住（页面 `.app-shell` 的 `z-index:1` 和页面根的 `isolation:isolate` 各自形成层叠上下文）。
- 第一版给结果图加了"显影"滤镜动画，出图瞬间的像素颜色不准，`test_gallery_image_loading` 抓到后去掉；完成提示只用光子环闪光。
- 第一版皮肤整份复制进每个页面样式，创作台首屏 gzip 超出 32,000 预算（`test_navigation_performance_contract`），见上表 `build_frontend.py`。
- 第一版用 `justify-content:center` 居中缩略图条，320px 宽时溢出部分被推到左侧够不着，第一张缩略图被"上一张"按钮盖住；改为首尾 `margin:auto`。

## 行为变化需要知道的

1. 任务进行时黑洞持续以 30 fps（手机 20 fps）渲染，而不是暂停。以前空闲时本来也是这个帧率，GPU 占用不超过空闲状态；
   用户在"场景 → 暂停光场"或系统"减少动态效果"时，仍只画一帧静止画面（直接显示加速后的亮度）。
2. 收藏/历史抽屉现在盖住整个视口（包括外壳顶栏）。

## 回滚

`git revert <本分支提交>` 后重跑三个构建器和 `python tools/build_frontend.py`，再走正式发布流程。Git 回滚不会改动线上服务器。
