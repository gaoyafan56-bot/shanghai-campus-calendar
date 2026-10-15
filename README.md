# 上海高校招聘日历

单文件 `index.html`，无须服务器或登录即可查看。点击日期弹出当天场次，支持学校、活动类型和关键词筛选，链接指向学校官网。已结束活动保留。

## 当前交付状态（2026-10-15，北京时间）

重新核查后，上大163场、上理52场、上海海洋10场已通过GitHub运行实测；原有9校继续采集。华政官网公告已核实并补录3场，GitHub服务器访问该校仍返回HTTP 403，因此其自动更新尚未恢复。

仓库由用户创建为公开仓库（用户同意使用免费版 GitHub Pages）。GitHub 插件写入授权已实测成功，完整文件已提交 main 分支。Pages 已成功部署，并实测公网 HTTP 200。访问：https://gaoyafan56-bot.github.io/shanghai-campus-calendar/ 。首次发布记录：https://github.com/gaoyafan56-bot/shanghai-campus-calendar/actions/runs/38740656523 。该运行的 deploy 作业成功；update 在首次发布时因4校来源失败显示红色，符合降级发布设计。失败邮件通知开关仍需由用户在个人通知设置中开启。

## 一次性操作清单

你已经有 GitHub 账号并已创建仓库，无须重新注册，也无须购买 Pro。

1. 登录 `gaoyafan56-bot`，打开 https://github.com/settings/installations 。这是个人账号设置，不是仓库 Settings。
2. 找到 ChatGPT/Codex 对应应用，点 Configure。在 Repository access 下选 Only select repositories，添加 `shanghai-campus-calendar`，Save。若没有对应应用，回 Codex 的 GitHub 连接设置走官方连接/安装流程；不要生成或发送 token。
3. 告诉 AI 已完成授权，由 AI 用连接器写入本目录文件。
4. 仓库 → Settings → Pages → Build and deployment → Source，选择 **GitHub Actions**。不选择 Deploy from a branch。
5. 仓库 → Actions → 每周更新招聘日历 → Run workflow → main → Run workflow。若页面提示先启用 Actions，点启用。
6. GitHub 个人通知设置 https://github.com/settings/notifications ：找到 Actions，开启 Email，选择只通知失败（如界面提供 Only notify for failed workflows）。验证接收邮箱。**首次手动运行请由你点击**，这样你会成为运行的触发者；定时运行通知接收还可能受最后修改定时配置的账号影响，需以实际失败邮件验收。
7. 运行结束后，在 deploy 作业/仓库 Pages 设置中打开 GitHub 实际返回的地址。预计形式为 `https://gaoyafan56-bot.github.io/shanghai-campus-calendar/`；在部署成功前不能视为可用链接。

免费范围：公开仓库、GitHub 标准托管 Linux runner、GitHub Pages；不配置付费大规格 runner、不购买域名、不接入收费服务。默认临时 Actions 身份由 GitHub 提供，源码不包含账号密码、token 或任何硬编码密钥。

## 文件

- `scrape.py`：13 校抓取适配器，数据源及详情规则写在注释和 `SOURCES`。
- `template.html`：单文件页面模板；`index.html`：含 `EVENTS` 数组的独立可打开页面，不依赖外部 CDN。
- `data/events.json`：持久化历史活动，不能每周删除。
- `data/status.json`：各校最近成功时间、数量和错误摘要。
- `data/health.json`：失败学校清单。
- `.github/workflows/update.yml`：更新、提交缓存、发布和失败报告。

## 抓取口径

每条记录严格为 `{d,start,end,co,venue,school,type,link}`。日期 YYYY-MM-DD，时刻 HH:MM，只公布开始时间时 end 为空。未公布开始时刻的活动跳过并写警告日志，绝不填 00:00。地点缺失显示“官网未公布”，线上活动写“线上”。类型仅宣讲会、双选会、招聘会。

上交/华师/上财：优先使用官网公开月历接口，已实测含完整日期和宣讲/招聘会详情路径；不把新闻发布日期当活动日期。上财列表保留 `?nrdm=allxjh1`。上财月历响应实际为 `data[].con[]` 嵌套数组。

上大/上理/上外贸：只尝试公开招聘日历，绝不访问需要登录的逐场详情 API；详情回退官方列表。上海海洋回退官方首页。动态兼容路径使用学校网页自己的数据解析，不硬编码学校前端加密密钥。遇到要求登录/验证码时停止该校。

上外/东华：分别调用公开宣讲会、招聘会接口并翻页，JSONP 用 JSON 解析，不能 eval。招聘会使用官网 `recruitment.html?wid=`，宣讲会：上外使用 `preaching.html?wid=`；东华已实测需加 `/page/` 前缀，使用 `page/preaching.html?wid=`，招聘会同样使用 `page/recruitment.html?wid=`。

同济：公开接口已改为返回真实官方详情 URL（含 `tjjyzx.tongji.edu.cn`），优先采用返回 URL，不强套旧 `newsDetail.html?id=` 规则。

华理：提取“召开时间/地点”并通过 ASP.NET 公共表单翻页，保留官网实际 `/student/RecruitmentDetail.aspx?id=` 路径。目前仅验证用户提供的宣讲会列表，不能据此保证该校其他独立招聘会栏目完整。

上电：解压官网公开 HTML，再安全解码 Base64，读取宣讲与招聘会列表及分页。日期范围内没有时刻的旧网络招聘会不编造时间。

华政：只使用日程列表里的真实活动正文中明确标注的时间，输出链接回退官方日程列表。当前 No Data，暂不可用。

月历接口覆盖上个月到未来两个月；其他列表按公开分页采集近期内容。历史记录从首次采集开始积累，不承诺补齐所有校历年活动，也不能承诺覆盖官网未公开/图片中/登录后才显示的排期。每周一更新意味着周中新增、改期、取消可能尚未同步，出行前请点官网核对。同一详情链接改期覆盖旧版本；列表回退没有稳定逐场 ID 时，改期可能留下旧记录，需人工核验日志。

## 自动运行与容错

配置：`0 0 * * 1`，未设置其他时区，UTC 每周一 00:00 = 北京时间每周一 08:00。

每校独立处理，请求20秒超时、最多3次重试；4个学校并行。某校异常时跳过该校，保留其历史数据、最近成功时间，页面显示未更新；其他学校继续更新。先保存/提交可用结果并上传网页，再把来源失败标记为 Actions 失败。独立 deploy 作业仍可发布这份降级页面，避免“单校失败导致所有数据停止”。严重安装/构建错误没有网页产物时，部署也会失败，旧站仍保留。

错误完整细节见 Actions 日志，页面只显示适合阅读的简短原因。失败不自动修复官网改版：收到邮件后把失败日志发给 AI，由 AI 修复对应适配器。持续无法访问的学校会每周继续报告失败，直到修好，不静默假装恢复。

GitHub 定时任务是尽力调度，可能延迟，不能保证08:00整点完成；极端负载下可能丢弃排队任务。公开仓库长时间无活动可能自动停用定时工作流；如停用，在 Actions 中重新启用。未触发的工作流没有失败运行，因此不能依赖失败邮件检测“根本没有运行”。本方案没有额外的付费调度监控服务。

## 验收清单

- [ ] 仓库 Code 中能看到 `scrape.py`、`template.html` 和 `.github/workflows/update.yml`，都在默认分支 main。
- [ ] Settings → Pages 的 Source 为 GitHub Actions。
- [ ] 手动运行一次，Summary 中有13校数量及状态；抓取失败显示红色，deploy 可单独成功，两者不矛盾。
- [ ] `data/events.json` 与 `index.html` 中的总条数一致。
- [ ] 页面可翻月、筛选学校/类型/关键词；点击日期弹出场次。
- [ ] 抽查上财一条活动日期、时刻、地点和官网详情一致；只公布开始时刻的 end 为空。
- [ ] 抽查至少一条双选会、线上活动和已结束活动。
- [ ] 4个暂不可用学校必须显示未更新，不能声称13校全部可用。
- [ ] 测试一次失败邮件；当前华政 No Data 本身可作为失败验收案例，不需人为破坏脚本。
- [ ] **2026-10-19（周一）北京时间08:00之后**查看 Actions：出现触发原因为 `schedule` 的运行；页面更新时间、提交记录同时变化。允许 GitHub 排队延迟；只有手动成功不能证明 schedule 已经触发。
- [ ] 已拿到 GitHub 实际返回的 Pages URL 并成功打开；预计 URL 不算上线验收。

## 本地复现（可由 AI 操作，你不需要安装）

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
python scrape.py
```

有任一学校失败时退出码1，但仍生成可用缓存和 HTML。`python scrape.py --render-only` 仅从缓存生成页面；`--school 上海财经大学` 可单独排查某校。

## 官方参考

- GitHub Pages 套餐：https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
- 定时触发与延迟限制：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- 配置应用仓库访问：https://docs.github.com/en/apps/using-github-apps/reviewing-and-modifying-installed-github-apps
- Actions 通知：https://docs.github.com/en/actions/how-tos/monitor-workflows/notifications

## 四校重新核查（2026-10-15）

- 上海大学：公开日历接口已恢复采集163场；使用学校官网公开模块解析响应，不复制密钥、不登录。
- 上海理工大学：同上，已实测52场。
- 上海海洋大学：同上，已实测10场；活动链接按约定回退官网首页。
- 华东政法大学：原日程列表为空，但官网通知公告提供可验证排期。本地读取成功，GitHub runner返回HTTP403。已补录9月23日13:30–15:30、10月20日09:00–16:30、11月4日13:30–15:30三场，官方原文链接保存在活动中；这些不能视为已恢复无人值守更新。

补录文件data/supplements.json仅存已核实的活动字段和官方链接；每次更新合并去重，已结束记录保留。官网公告若能在runner中读取，采集器会继续尝试自动更新。缺失年份的11月4日活动按2026年9月30日公告上下文及周三日期核对，未将2027届毕业年份误作活动年份。
