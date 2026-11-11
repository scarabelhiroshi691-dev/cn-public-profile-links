# 公开账号关联首版使用说明（Codex 内试用）

当前为 **2026-11-11 Codex 内试用版**，沿用 11 月 10 日确认的首版定位。使用时在项目对话里直接发昵称或公开链接。Codex 负责浏览、审阅归属和整理报告，程序负责保存任务、来源和恢复位置。

一次完整使用是「给入口 → 查候选 → 必要时补一条公开线索 → 确定起始账号 → 读取有限公开资料 → 核对明确关联 → 导出报告」。结束时会明确说明确认了什么、哪些未确认，以及实际查了多大范围。它不能保证每个账号都有可确认的站外信息。

## 首版怎么用

可以直接复制这句，把平台和昵称换成你的目标。

> 用公开账号关联首版查 B 站昵称「示例创作者」。确认账号后，请整理公开简介、最多 3 条作品和能核实的站外账号。每条附来源，把待核对的线索单列。

### 支持哪些入口

| 手上有什么 | 怎么发给 Codex |
| --- | --- |
| 小红书、B 站或抖音的公开昵称 | 发「昵称＋平台」查站内用户。抖音也可用准确的公开抖音号搜索。 |
| 已知的公开主页 | 直接发主页链接。Codex 从该页核对公开昵称和账号标识；资料以实际能打开的页面为准。 |
| 一条公开作品链接 | 发小红书笔记、B 站 BV 视频或微信公众号公开文章的直接链接。Codex 从作品页核对实际作者或发布方，再沿可核实的公开来源继续。 |

B 站从昵称起步时，可用原昵称查站外本人公开声明，并核对是否指回实际已读的 B 站 UID。确认账号后也可沿本人公开声明读取 GitHub 和 YouTube 主页。其他平台线索按已读来源和实际可访问情况记录。公众号文章可按给定链接读取，短长链和仓库跳转的专项验收暂缓。

### 只给昵称时

小红书、B 站和抖音先查一轮站内用户结果，默认最多保存 10 个候选、读取 3 个主页。报告写明实际可见、保存和已读范围，过滤和访问受阻另列。抖音通过实际用户搜索卡进入主页，报告把「结果未读」「已读但缺证据」和「已确认」分开。

| 查到什么 | 怎么继续 |
|---|---|
| 当前范围内没找到匹配 | 写明已查范围。若一条公开线索可以继续核对，只问这一条。 |
| 找到多个精确同名 | 保留各自的主页和账号 ID，复核后仍无法区分就只问一条公开线索。 |
| 找到一个精确同名 | 核对实际主页及标识，再决定是否可以固定目标账号。 |
| 页面需登录或验证 | 保留访问状态。用户在可见共享浏览器完成验证后，从原任务继续。 |

### 补一条公开线索后

遇到同名或近名，按提示**在原对话补一条**能指向目标本人的公开线索。可以回复「请用这条公开作品〈链接〉接着核对」。原昵称、候选和证据会保留，实际作品的作者入口用来核对目标主页。

- **B 站**给一条目标本人发布的 BV 视频链接。
- **小红书**任选其一，给一条公开笔记链接、准确作品标题或准确小红书号。标题只查首批最多 15 张作品卡。同题仍无法区分就保留待核对。小红书号只在已保存候选里精确比对。App 分享短链可先正常打开，取得实际笔记页地址。

确认作者后，可要求整理公开简介和最多 3 条作品。B 站用来澄清的那条视频计入 3 条。职业或经历来自本人简介时，报告标为账号自述，并附来源和读取时间。

### 评论中有具体账号线索时

可直接说「请看已读笔记的公开评论和本人回复，沿明确的账号声明或共同作品线索只扩展一层，逐条附来源」。Codex 先有界读取并登记实际评论，记录已读数量、折叠回复和未读范围。评论读取由 Codex 操作浏览器完成，目前没有独立的全量评论采集命令。

本人回复若明确声明大号、小号，并给出唯一准确的小红书主页链接，程序会安排优先读取该链接。其他优先评论可读取署名主页。每任务最多 3 个不同落点，只扩展一层。优先读取后仍需核对原文、署名和目标主页，才能登记明确的账号关联。普通问答、歌词或含糊留言只记录互动和解释线索，不能据此确认现实私人关系。

### 怎么读跨平台证据

| 报告里看到什么 | 怎么理解 |
| --- | --- |
| **已确认的起始账号** | 已打开对应主页，核对了账号标识。补过作品时，可以沿作品的作者入口回查。 |
| **已确认的站外关联** | 已审阅本人原文中的明确声明或公开链接，也实际读到了对应的目标主页。每条附声明原页、目标主页和指向的方向。 |
| **单向声明或双向互链** | 一边写明账号或放了链接，就按该方向记录。两边各有证据时分方向列出。双方链接都实际通向准确主页时，才标为可点击互链。 |
| **待核对** | 同名候选还分不清、只有项目链接或第三方提及、本人声明可读但目标页打不开等。报告保留线索和来源，并写明缺的是哪一步。 |
| **当前范围没找到** | 写明看了哪些搜索结果、主页和作品。在这个范围内没有足够线索可以继续。 |

可直接说「请导出这次报告」。报告可保存为 Markdown 和 JSON，初始版和补线索后的版本可分别回查。

### 一句话跑到交付

> 用公开账号关联试用版查小红书昵称「〈昵称〉」。先查候选，重名时只问我一条公开线索。定位后读公开简介和最多 3 条笔记，必要时核对公开评论中的具体账号声明，只扩展一层。最后导出 Markdown 和 JSON，分开写已确认、待核对和未读范围，每项附原始来源与读取时间。

报告中的来源应能回到对应主页、作品或评论所在笔记。动态页面可能需要登录、展开评论或重新从主页进入；报告会同时保留账号标识、作品标识及评论位置。真实登录和验证码由你在共享 Chrome 中处理，完成后从原任务续办。当前仅受控恢复检查通过，真实触发后的恢复仍待现场验证。

首版范围和待验证项见仓库 README 与 RELEASE_NOTES.md。以下为维护者命令，日常使用直接发上面的自然语言请求即可。

## 维护者操作

程序位于 `F:/codex/Projects/public-profile-links`，默认账本目录为 `runs`。账本使用 Python 标准库，浏览器读取使用既有 Node、Playwright CLI 和共享 Chrome。归属判断由 Codex 审阅后写入账本。

## 创建、恢复和导出

在本项目目录使用 PowerShell：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python scripts/profile_task.py create --label '公开创作者核验' --kind profile --platform '小红书' --value '已取得的完整公开主页链接'
python scripts/profile_task.py resume TASK_ID
python scripts/profile_task.py export TASK_ID
```

`create`返回12位任务ID。若使用独立账本目录，每条命令都在子命令前加同一个 `--state-root 实际目录`。`resume`只返回进度，`xhs-run`才执行／继续正常小红书UI动作。`export`在账本目录下的 `reports/TASK_ID` 写入当前版本的 Markdown 和 JSON。默认账本目录为 `runs`。输入可选 `nickname`（必带平台）、`work`及`profile`。程序生成和调度查询，其他公开网页搜索由Codex调用现有工具并审阅结果；没有独立搜索API或模型API。

## 小红书昵称统一执行入口

先预检共享Chrome；未打开时使用既有全局启动脚本和原资料，不使用FreshOpen。先把选样先验和本轮上限存为 `F:/codex/Temp/prior.json`，例如：

```json
{"sampling_prior":"只收到公开昵称和平台","limits":{"queries":8,"profiles":10,"depth":2}}
```

再创建昵称任务并分步执行。

```powershell
$env:TEMP='F:/codex/Temp/public-profile-runtime'
$env:TMP=$env:TEMP
node scripts/shared_browser.mjs preflight
python scripts/profile_task.py create --label '本轮站内核验' --kind nickname --platform '小红书' --value '公开昵称'
python scripts/profile_task.py discovery-config TASK_ID --data-file F:/codex/Temp/prior.json
python scripts/profile_task.py xhs-run TASK_ID --steps 2 --max-candidates 10 --max-profiles 3
python scripts/profile_task.py resume TASK_ID
python scripts/profile_task.py xhs-run TASK_ID
python scripts/profile_task.py next TASK_ID
```

执行器新建自己的任务标签，原样输入昵称、切“用户”、读取本次渲染的用户卡和有界主页元数据。它不自动滚动遍历、不检查全部作品或简介、不固定根节点、不确认账号或MCN关系；`awaiting_review`表示采集结束后待审阅。`--steps`限制本次步骤数，重复使用同一任务ID继续；不因恢复重复提交已经落地的搜索。

初次`--max-candidates`（1–20，默认10）、`--max-profiles`（0–10，默认3）形成本轮固定范围；后续同任务参数不会重定义它。任务总主页额度通过`discovery-config`的`limits.profiles`调整。每次新读取前检查当前总额度，额度耗尽时`xhs_executor.hold`为`budget_exhausted`，候选与恢复位置仍在；调整总额度后再次`xhs-run`继续固定范围内的队列。

`stop`保存后不会发起下一浏览器动作，须显式`stop`提交`{"reason":"用户要求继续","reopen":true}`才继续。已经在途的动作无法撤回，其实际结果仍记录。磁盘写入失败或不相关并行改动会停止提交并保留意图；先检查账本，不能重新创建任务掩盖中断。任务标签有所有权标记并核对URL，标签被关闭或移位会停止，不接管其他任务标签；打开／读取页面后但记账前崩溃可能留一个任务标签，不承诺导航严格只发生一次。

执行状态`blocked`时先检查具体原因。用户实际处理登录或验证码后，才可显式重试：

```json
{"reason":"用户已在可见共享浏览器完成认证","authentication_resolved":true}
```

```powershell
python scripts/profile_task.py xhs-retry TASK_ID --data-file F:/codex/Temp/retry.json
python scripts/profile_task.py xhs-run TASK_ID
```

普通浏览器故障修复后的重试只需真实`reason`。每个中断步骤最多显式恢复一次，查询还受既有单次重试上限限制；不自动重试认证。恢复成功后当前阻断字段清理，失败尝试与历史缺口保留。

报告分别记录可见条目数（可含重复）、可收录唯一候选数、已保存候选数、过滤数、已处理主页及成功读取数。`result_state:filtered`表示有卡片但未收录，不能写为没有搜索结果；被过滤的联系值不保存。平台明确标注的小红书号按平台标识保存，11位数字也不据此用作联系方式。

`next` 的 `nickname_outcome`、`resume` 或 `xhs-run` 的 `discovery.nickname_outcome` 与 Markdown 的「昵称查找结论」使用同一份判断。`not_found_in_scope` 表示本轮站内或保存范围未找到匹配候选，`ambiguous_same_name` 表示已保存多个待区分的精确同名账号。单个同名候选仍待归属核对。过滤与访问受阻单独显示。`scope` 列出已见、保存、已读和完整列表标记。

已读候选完成必要复核、队列没有可执行动作且仍无法定位时，使用唯一的 `question` 向用户请求一条公开区分线索。问题为空时依据现有动作或访问缺口交付。同一任务没有新信息时避免重复提问。需要记录已读候选仍待区分时，用 `candidate-review TASK_ID --data-file 实际文件` 提交例如 `{"candidate_id":"C1","status":"unconfirmed","note":"已读主页，当前昵称不足以区分"}`。复核后再看 `next`，确认 `question` 有值就先 `export TASK_ID` 留下补线索前的版本。

### 在原任务续办一条补充线索

用户答复后，用原任务 ID 记录一条线索。`kind` 取 `work_title`、`work_url`（小红书直接作品页链接）或 `platform_id`（准确公开小红书号），`value` 使用该条原始线索。例如将下列内容存为 `F:/codex/Temp/clue.json`，并换成实际作品页链接：

```json
{"kind":"work_url","value":"https://www.xiaohongshu.com/explore/abc123"}
```

```powershell
python scripts/profile_task.py xhs-clarify TASK_ID --data-file F:/codex/Temp/clue.json
python scripts/profile_task.py xhs-run TASK_ID
python scripts/profile_task.py next TASK_ID
```

作品标题只查一次，检查首批最多 15 张作品卡，打开精确作品后沿实际作者链接读取主页。同一作者链接的跟踪参数不影响去重。准确 ID 只比对原任务保存的候选，唯一匹配时重读原主页。命中后，`next.clarification` 同时给出候选编号 `candidate_id`（如 C1）和账号编号 `entity_id`（如 A1）。打开实际来源和作者主页核对后，保存 `{"entity_id":"A1","reviewed":true,"basis":"实际作品作者入口与已读主页对应，公开账号 ID 一致"}` 到复核文件，再用 `fix-root TASK_ID --data-file 实际文件` 固定账号。`entity_id` 取本次结果里的实际账号编号。`clarification` 及 Markdown 的「补充公开线索」保留每次来源、范围及结果，原昵称输入和已有候选、证据仍可查。

中断后用 `next` 查看阶段。认证由用户本人完成，再用 `xhs-clarify-retry` 提交真实 `reason` 及 `authentication_resolved:true`，再运行 `xhs-run`。普通失败复核后只需真实 `reason`。每个失败步骤最多显式重试一次。已保存线索按原任务续办，避免重新登记同一输入。

### 核对账号后的公开资料

`next` 出现 `materials` 后，在同一任务用 `xhs-materials TASK_ID` 一次读取一个来源。先核对实际主页的公开账号 ID 和主页标识，再在首次渲染的作品区选取最多 3 个不同作品，依次打开实际链接并核对作者。可用 `next` 或 `resume` 查看待复核的页面编号、剩余来源或中断原因。

命令返回的 `preview_for_review` 供当次复核。原始预览不写入账本。根据实际读到的内容，以 `xhs-materials-review TASK_ID --data-file ...` 逐页提交精简、非敏感的条目，例如：

```json
{"page_id":"P2","reviewed":true,"items":[{"kind":"occupation","summary":"在简介中自述曾从事软件开发"}]}
```

主页支持 `bio` 和 `occupation`，作品支持 `work` 和 `occupation`。职业只写明确的本人自述，保持原有时间限定。作品写实际所见标题或正文要点。没有可纳入内容时提交空 `items`。如果预览丢失，可用已保存来源复核可见页面后提交。导出从页面记录生成逐条来源链接和读取时间，同时展示未读、失败及待复核状态。

访问认证由用户本人处理。核对中断原因后用 `xhs-materials-retry` 提交实际 `reason`，若为认证再加 `authentication_resolved:true`，然后继续原任务。每个中断来源最多显式重试一次。公开内容涉及明确未成年人线索时，当前来源标为超出汇总范围。有限翻页暂缓。

### 导出后逐条回查

使用 `export TASK_ID` 导出当时版本。补线索前后的版本可分别打开。先在「昵称查找结论」核对原站内范围，报告开头的「新增候选」统计起始账号之外的候选。例如保存 10 个候选、固定其中 1 个后，开头会显示 9 个，原站内范围仍显示保存 10 个。

依次打开「补充公开线索」里的实际作品与已核对主页，核对作品作者及公开账号 ID。再逐条打开「已核对账号的公开资料」的来源。报告有跨平台关系时，沿关系引用的证据编号到「证据」打开每个方向的原文和目标页。回查时遇到访问限制，就登记本次缺口。

## 昵称／作品发现闭环

先创建任务，再用数据文件调用`discovery-start`，记录选样先验和本轮范围：

```json
{"sampling_prior":"只知道公开昵称及平台，尚未看过目标主页","limits":{"queries":8,"profiles":10,"depth":2}}
```

```powershell
python scripts/profile_task.py discovery-start TASK_ID --data-file F:/codex/Temp/start.json
python scripts/profile_task.py next TASK_ID
```

`next`是只读动作清单：`public_search`交给Codex现有公开搜索工具，`read_profile`核对真实URL与标识，`review_attribution`只核对候选到输入／已知根节点的归属，不从候选简介继续扩散。给定准确主页时先读取，不制造搜索。未找到目标时允许保持根节点为空。

`public_search`按`channel`选择渠道：默认`public_web`使用公开网页检索；`xiaohongshu_ui`须在正常共享Chrome站内搜索框输入原样昵称，不附引号或`site:`。新的小红书昵称任务优先使用上节`xhs-run`自动创建并执行该查询。历史手工查询仍可用`query`与`search-result`记录，但已完成的旧查询不能被新执行器重放；另建有明确先验的本轮任务。

搜索完成后，仅写入经过筛选的非敏感结果；不要复制原始摘要全文：

```json
{"query_id":"S1","status":"done","results":[{"platform":"示例平台","url":"https://example.org/creator","nickname":"公开昵称","source_url":"https://example.org/creator","reason":"准确昵称搜索命中；归属待核对"}],"note":"仅索引线索，未打开主页"}
```

使用`search-result`保存上例；无结果时`results:[]`。可用状态还包括`timeout`、`failed`、`login_required`、`verification_required`。结果不能覆盖重放。零命中只表示本渠道本次未命中。

读取后用`fix-root`记录`entity_id`、`reviewed:true`及`basis`，说明为何与原始输入对应。它要求主页已读且有观测标识。根节点固定后不能无提示换人。`candidate-review`接受`candidate_id`、`status`和`note`；状态可为`unconfirmed`、`conflict`、`excluded`、`declaration_only`、`pending`，确认只能走证据与`relation`。

需要调整查询时用`query`：`terms`为1–3条原样公开线索，另带`purpose`和可选`platform`／`channel`。无根节点的初始查询仅能使用原始输入，可去掉平台限制；沿新线索调整时必须带`source_entity`和已读、已审阅的`evidence_ids`，每个词都须出现在相应公开观察中。仅已确认根节点／账号可提供扩展线索。未知候选可以核验归属，不能提供新公司或别名继续扩散。

直接链接无需再搜索：先建目标`entity`与实际审阅的`evidence`，再用`candidate`保存`platform`、`url`、`source_url`、`source_entity`、`evidence_id`和`reason`。证据目标须与候选一致。只知道公开标识而没有准确URL时可省略`url`，保留`nickname`或`platform_id`与来源，不猜主页地址。

默认最多8条不同查询、10个主页尝试、2轮扩展。连续两次同分支同渠道完成查询且无新增候选时停止该分支；认证只暂停相应渠道，不绕过验证，其他独立公开分支可继续。超时保留为超时，不冒充无结果。`stop`保存`reason`，恢复须显式提交`reopen:true`及原因。`query-retry`接受`query_id`及`reason`，每条中断查询最多显式重试一次，旧记录保存在`attempt_history`。认证中断还须用户本人实际完成认证，再记录`authentication_resolved:true`；程序不能验证用户身份或代为完成认证，不得仅为解除暂停而填写该字段。

候选按准确URL或平台标识去重，同名不合并；同一目标的不同发现来源都保留。`confirmed_new_accounts`是历史兼容字段，表示根节点外明确关联的公开主页（可包括作者网站），不能直接称社交账号数；评测另列网站与社交账号。`read_profiles`包括起始、候选和作者网站的资料区已读数，不表示身份都已确认或全部历史作品均已覆盖。

### 小红书昵称的站外原文补查

原昵称站外查询未读到本人原文时，可在同一任务做一次有明确依据的补查。站内唯一精确昵称候选的主页已实读时，可以用页面实际显示的小红书号找旧昵称下的声明。若实际命中播客等出版物目录，可用所见节目名定位发布者原文，即使目录详情打不开。两种线索只用于本次候选核对。记录原查询、补查词和来源，保留原同名候选。

读到本人明确声明后，打开原文链接或明列账号的实际主页，核对准确小红书号及声明方向，再按已审阅证据记账。带主页短链的原文可用实际跳转核对目标。目录摘要、同名或主页未读时继续待核对。此步由 Codex 调用公开检索并审阅。


## B 站昵称与一条作品线索

创建 `nickname` 任务，平台填 `B站` 或 `哔哩哔哩`。使用共享 Chrome：

~~~powershell
python scripts/profile_task.py create --label 'B 站公开昵称核验' --kind nickname --platform 'B站' --value '公开昵称'
python scripts/profile_task.py bilibili-run TASK_ID
python scripts/profile_task.py next TASK_ID
~~~

首轮只看用户结果初始页，按公开数字 UID 去重，最多保存 10 个候选、读取 3 个主页。`next` 区分当前范围未找到、同名或近名歧义、访问受阻和待审阅。只有一个精确候选时，由审阅者核对主页与公开来源。排序或同名不能代替确认。

首次 `bilibili-run` 后先看 `next`。完成初始主页读取后，`bilibili-reverse-start` 在原任务登记一轮查询。接下来由 Codex 执行 `next` 给出的 `bilibili_reverse_web` 查询。只使用原昵称，最多保留 3 个原始来源。网页检索工具负责查询，程序保存查询、证据、候选及结果。

~~~powershell
python scripts/profile_task.py bilibili-reverse-start TASK_ID --data-file 空JSON对象所在文件 --revision 当前版本
python scripts/profile_task.py next TASK_ID
python scripts/profile_task.py bilibili-reverse-result TASK_ID --data-file 已审阅结果所在文件 --revision 当前版本
python scripts/profile_task.py next TASK_ID
~~~

结果文件包含 `query_id`、`status`（`done`、`failed` 或 `timeout`）、`note` 和 `sources`。每个来源填 `source_url`、`status`（`verified` 或 `pending`）及 `note`。已核对的来源另填实际读到的站外 `profile_url`、`profile_id`、`profile_checked_at`（带时区）、原声明指向的 `bilibili_url`、`attribution:"self"` 和 `reviewed:true`。作为声明发布账号，目前支持实读的 GitHub 或 YouTube 及其本人发布的页面。仓库文件须复核所有者和第一人称归属语境。来源是个人网站但作者与站外账号无法直接核对、只有摘要、对端不可读、或未见准确 B 站主页地址时，按 `pending` 记录缺口。失败时 `sources` 留空。

程序核对原候选中实际读过的 B 站 UID。唯一精确昵称且反向声明命中时，可以在同一次审阅里固定起始主页并记录站外 → B 站的单向关联。同名候选仍无法区分时沿用一条公开 BV 视频线索。执行失败留待核对，必要时沿用 `query-retry` 显式恢复，最多一次。

如果同一份已审阅的本人原文同时列出小红书号，在该 `verified` 来源增加 `xiaohongshu_id`。按 `next` 定位实际小红书主页，只有账号号时走正常站内用户筛选。在同一 B 站任务用 `entity` 登记实际主页链接，然后用 `read` 指定实际打开的共享浏览器标签和地址。实体无需预填小红书号，由主页可见账号区读取。

~~~powershell
python scripts/profile_task.py read TASK_ID --entity 小红书实体编号 --tab 实际标签序号 --expect 实际主页地址
python scripts/profile_task.py bilibili-reverse-xhs-review TASK_ID --data-file 核对文件 --revision 当前版本
~~~

核对文件填原声明的 `source_url` 和实读小红书的 `entity_id`。主页显示号和原文一致才确认。没找到可读主页时用 `source_url` 和 `note` 记录具体缺口。报告保留同一原文分别指向 B 站与小红书的两条声明方向，两边未直接链接时按同主体声明呈现。

`question` 有值时只问一条可公开访问的 B 站视频链接。先导出当前版本。把用户给的直接 BV 视频页填入线索文件，继续用同一个任务 ID：

~~~json
{"kind":"work_url","value":"用户给出的 https://www.bilibili.com/video/BV…/ 链接"}
~~~

~~~powershell
python scripts/profile_task.py bilibili-clarify TASK_ID --data-file F:/codex/Temp/实际线索文件.json
python scripts/profile_task.py bilibili-run TASK_ID
python scripts/profile_task.py next TASK_ID
~~~

作品作者区只指向一个 UID，且实际主页 UID 核对一致时，`clarification` 给出待审阅的候选、账号、作品页和证据编号。按原文审阅后用 `fix-root` 固定相应账号，再导出。该 UID 已在原候选中时追加来源，在原范围外时追加候选。两种情况均可回查首次搜索及旧证据。已完成且留有 `bilibili_ui` 查询的未确认旧任务也可用同一个 ID 接续。

`bilibili-run --steps 1` 可只执行下一动作。遇到访问中断先看 `next`，需要登录或验证码时由用户本人在固定浏览器处理，再用 `bilibili-retry` 记录实际恢复原因及 `authentication_resolved: true`。普通中断可记录原因显式重试一次。候选发现限初始结果页。

确认作者后，在同一任务再次执行 `bilibili-run TASK_ID`。读取已确认主页的简介和最多 3 条公开视频，已核对的补充视频计入这 3 条。每条视频核对作者 UID，并保存发现来源、简介中观察到的公开链接及读取时间。

现有站外核对支持公开 GitHub 账号和 YouTube `@handle` 频道。`next.materials.reviewable` 给出已读的声明原页与目标主页。对照原页确认是本人声明后，用 `bilibili-link-review TASK_ID --data-file 实际文件` 提交 `source_url`、`target_url`、`reviewed: true` 和 `basis`，再运行 `bilibili-run` 沿已审阅的账号继续。本轮最多读取 6 个不同站外主页，作品链接单独保留。遇到账号后续读取的验证或中断，以 `next.materials` 为准，用 `bilibili-materials-retry` 显式恢复，真实验证由用户本人完成。`export` 输出逐条来源和待核对项。

## 抖音昵称与公开用户卡

用 `nickname` 创建抖音任务，再执行正常浏览器搜索和主页读取。准确公开抖音号也可作为搜索词。

```powershell
python scripts/profile_task.py create --label '公开抖音账号核对' --kind nickname --platform '抖音' --value '公开昵称或抖音号'
python scripts/profile_task.py douyin-run TASK_ID --max-candidates 10 --max-profiles 3
python scripts/profile_task.py resume TASK_ID
python scripts/profile_task.py export TASK_ID
```

执行器保存实际搜索来源和候选卡，按主页地址去重，从实际搜索卡进入主页并记录落地页。`resume` 查看状态。遇到访问中断，按 `next` 在同一个任务登记 `douyin-retry` 的原因，然后重跑 `douyin-run`。若浏览器明确要求登录或验证，用户在共享浏览器完成后才在重试数据里登记 `authentication_resolved: true`。

搜索结果区未取得内容、或候选主页未读取时显示「结果未读」。已打开主页、仍缺准确的本人归属证据时显示「已读但缺证据」。只有按现有证据流程审阅本人原文、核对它所指的实际主页并登记确认关系后，才显示「已确认」。每条声明保留原方向。

## 已读评论的线索筛选与一层复核

在已有任务中登记已读评论，Codex 根据具体公开语境审阅优先级。程序先用少量语句特征安排初始顺序，用户指定的留言可以优先复核。歌词或文案来源另存为解释线索。优先级决定下一步先看哪条，关系状态依据公开证据审阅。

```powershell
python scripts/profile_task.py comments-record TASK_ID --data-file 已读评论.json
python scripts/profile_task.py comment-review TASK_ID --data-file 评论审阅.json
python scripts/profile_task.py next TASK_ID
python scripts/profile_task.py comment-run TASK_ID
python scripts/profile_task.py export TASK_ID
```

`comments-record` 的 `page_id` 必须指向本任务起始账号已读且作者已核对的笔记。每批至多 100 条，每任务至多 200 条。数据包括 `read_at`、`displayed_total`、`end_visible`、`remaining_replies` 和 `comments`。每条评论保存 `id`、`author_url`、`nickname`、`content`、`date` 和可见的 `links` 数组。时间沿用实读记录，非文字内容保留缺口。重复登记按笔记和评论 ID 去重。

没有渲染出评论或总数时，先确认是否仍在加载。只有明确空状态才能记录零评论；空白或加载超时保留未核实。`end_visible` 可记录明确的空状态或列表结束。无文字的表情／图片条目只能算已保存条目，未读其内容时须单列缺口。语句摘要避免自带句末句号，报告会统一补上。

`comment-review` 包括 `lead_id` 和 `reason`，可用 `priority` 指定 `priority` 或 `normal`，用 `quote_source` 保存核对过的公开歌词或文案来源。明确的用户优先标记可与该来源并存。本人回复明确标注大号、小号等，并含一个准确的小红书主页链接时，自动列为优先复核。多个主页链接时，由 Codex 审阅后在 `target_url` 中选择原文实际给出的一个。审阅由 Codex 根据原始上下文完成。

`next.comments` 给出优先队列。`comment-run TASK_ID` 每次读取一个已保存的优先评论直接指向的小红书主页。本人回复读取正文中选定的账号链接，其他评论默认读取其署名主页。使用共享 Chrome，保存准确主页标识及公开简介／作品区的可见状态。读取前记录意图，返回后一次性保存页面和一层记录。再次执行时跳过已完成项。具体公开声明仍由 Codex 按原文审阅，报告按已审阅的账本关系显示当前状态，并保留读取时记录。

`next.comments.reader` 显示读取状态。中断或访问失败后，先核对失败原因及条件变化，再用 `comment-read-retry TASK_ID --data-file 重试说明.json` 登记 `lead_id`、`reason`，随后重新执行 `comment-run`。遇到真实登录或验证，用户完成后在重试说明中登记 `authentication_resolved: true`。两次未成功后保留待处理。

读取只沿原评论署名主页或正文实际出现的公开链接进入一层，每任务最多 3 个不同落点。其他已观察到的公开链接由 Codex 使用现有浏览器读取及 `entity`、`read` 或 `page-read` 登记实际落地页，再用 `comment-expand` 保存 `lead_id`、`target_url`、`page_id` 和 `observation`。新落点的评论不能作为二层扩展来源。

`comment-run` 成功后已经保存一层读取记录，无需再调用 `comment-expand`。后者供已用浏览器手工实读并登记页面的替代路径。读取成功后仍按下方 `evidence`、`relation` 步骤审阅本人原文和目标标识，导出前检查这两步是否完成；没有足够证据则保留待核对。

页面访问受阻时仍保存读取状态和恢复条件。公开合作、作品归属或同主体关系需按原证据流程另行审阅，每条保留来源。

## 从一条公开作品链接起步

微信公众文章、B 站直接 BV 视频页和小红书公开笔记均可作为作品入口。链接必须指向真实作品，保留分享链接必要参数。

~~~powershell
python scripts/profile_task.py create --label '作品核验' --kind work --value '公开作品链接'
python scripts/profile_task.py work-run TASK_ID
python scripts/profile_task.py next TASK_ID
~~~

`work-run` 保存作品、发布者、原文里看到的公开链接和实际访问状态。公众号文章有可见的「阅读原文」时，会通过正常浏览器操作核对实际跳转。`next` 和报告将它单列为原文到落地页的单向观察，落地页未打开则保留待核对。实际跳转可供审阅，落地页和账号仍各自核验。

先沿已读的作者入口核对真实账号并记录主页。再用 `work-review` 提交 `url`、`entity_id` 和 `basis`。公众号文章缺可读账号主页时，关联到已核实账号还要提供 `evidence_ids`，由公众号原文指向本人页面的已审阅证据和账号作者处指回该篇原文的证据共同支持。缺反向原文证据，或仅有同名、第三方提及时，留待核对。经审阅后用 `fix-root` 固定起始账号。

「阅读原文」落到博客园文章时，先从文章署名区打开作者主页，建立对应的 `博客园` 实体。用 `read TASK_ID --entity ENTITY_ID --tab INDEX --expect 实际URL` 分别读取作者主页和同一篇博客园文章。文章地址中的作者标识、已读文章的署名链接及已读主页须一致。再分别记录公众号到博客园文章、博客园文章指回同一公众号原文的已审阅证据，供 `work-review` 使用。

如果公众号反链与输入地址一个是短链、一个是长链，用 `work-run TASK_ID --url 实际反链 --source 实际声明页` 读取反链。双向审阅只有在两个地址的实际文章都已读，且公众号标识、文章编号和篇次一致时，才接受不同地址为同一篇。分别保留原始链接和读取状态。

沿实际来源找到另一作品时，用 `work-run TASK_ID --url 作品链接 --source 实际来源`。需要保留另一路线或独有资料时，用 `work-note` 提交 `work_url`、`from_url`、`source_url`、`observation`。用 `work-review` 分别核对已读作品与账本中的已确认发布者。对端打不开时原线索和读取缺口仍可导出。上次动作只留意图时，可对同一链接显式使用 `--retry`。

各入口分别建任务。用 `work-compare TASK_A TASK_B TASK_C` 按准确标识汇合共同账号和作品，输出各任务的发现路径、独有资料和待核对项。用 `export TASK_ID` 导出单路 Markdown 和 JSON。

跨任务汇总公众号文章时，两边都要有实读记录，且记录中的公众号标识、文章编号和篇次一致，同一篇才合计一次。原始地址、发现来源及读取记录按任务保留。同一任务内另有已实读核对的同篇地址时，汇总把它附在该作品下。旧记录缺实读标识时，已核对归属的作品按任务单列。

## 记录证据

修改命令统一为 `python scripts/profile_task.py 操作 TASK_ID --data-file F:/codex/Temp/.../fields.json [--revision 当前版本]`。数据文件只放实际审阅后的结构化字段，不能输入原始网页、图片base64、微信号、个人二维码或无关个人资料。常见联系值检测只是辅助，不保证识别所有敏感内容，仍需先人工／模型筛选。

主要操作：

| 操作 | 数据字段与用途 |
|---|---|
| `entity` | platform、url，可带nickname、platform_id、internal_id、kind(account/institution)；同名不合并 |
| `page-read` | entity_id、reading（浏览器`inspect`原始元数据，不包含preview）；核对作者与来源后存入本轮页面记录 |
| `observe` | entity_id、status、observed_url及实际读到的标识；status为read须有观测标识 |
| `evidence` | source_url、source_entity、target_entity、type、observation、access_status；确认所需reviewed、attribution、matched_identifier／linked_url等由审阅者填入 |
| `relation` | from、to、kind(account_link/mcn/wechat_source/business_subject)、status、evidence_ids，可带note及current_validity |
| `gallery` | url、images:[{index:1,source_image:公开图片URL或null},...]；必须按页码连续，未加载图片仍保持pending |
| `review-image` | gallery_id、index、status(reviewed/unreadable)、source_image、observation；可带duplicate_of，例如G1:2 |
| `queue` | url、purpose，可带status(pending/done/login_required/verification_required/failed)、note |
| `gap` | platform、status、note；企查查缺口默认保留，需用户后续授权和真实读取才另作核验 |
| `legacy` | path：本项目test-runs中的历史JSON；保存引用与哈希，不自动继承确认结论 |

确认不是搜索命中：两端公开资料区须已读且标识对应，证据已审阅、不是摘要，准确目标匹配；关系必须连接到已知根节点。仅同名、作品相同或普通合作不能确认账号／MCN。`wechat_source`表示声明来源关系，不表示微信当前有效；证据还须标明`entry_role:personal`，不能用团队助手或群入口替代；不计入新增社交主页数。

MCN支持创作者到机构的本人声明（`attribution:self`），以及机构到创作者的原始签约声明（`attribution:institution`）；证据保留真实方向，关系按创作者→机构记录。两者均须`type:mcn_statement`、`declared_relation:signed_or_agency`和准确目标链接／标识。`business_subject`只表示账号明确披露法律主体，须`business_disclosure`、`attribution:self`和`declared_relation:disclosed_legal_subject`；不能替代企业结果卡、详情页或登记来源复核。

图片准确号证据`exact_id_image`还须记录`source_image`和`image_index`；来源帖子须已有同图源、同图序的`review-image:reviewed`记录。只捕获、OCR命中或填入`reviewed:true`不能通过确认。旧alpha若曾有缺少逐图来源的确认，需要补审；不会通过旧标签自动豁免。证据可另带`channel`与`content_date`，日期未知保留未知。

新的端点读取出现限制时，相关关系降为待复核，历史确认保存在relation.history。重复导入画廊不会清掉已看图；签名地址变化按同一已观察图片资源标识核对，资源本身变了会停止。接口尚未支持任意平台画廊。

## 共享Chrome

```powershell
node scripts/shared_browser.mjs preflight
node scripts/shared_browser.mjs tabs
node scripts/shared_browser.mjs inspect --tab 实际序号 --expect '实际公开URL'
node scripts/shared_browser.mjs step --tab 实际序号 --expect '实际笔记URL' --index 当前图序
python scripts/profile_task.py read TASK_ID --entity A1 --tab 实际序号 --expect '实际公开URL'
```

`read`把适配器返回的元数据、作者核对及配图队列一次写入任务；不保存正文或图片数据，不自动确认关系。读取失败保留原有证据并登记未完成项。序号每次重新查询，不能长期固定。URL或图序不符、会话关闭、验证或图片未稳定时停止，不会改用其他资料目录。会话关闭后，由助手用 `D:/Codex/Tools/Browser/Start-CodexBrowser.ps1 -Url 实际链接`复用原资料重新打开，再查询序号与进度。不要使用FreshOpen，也不要自动关闭其他任务。

### 图片仅内存传递（Codex Node REPL）

```javascript
var bridge = await import('file:///F:/codex/Projects/public-profile-links/scripts/codex_browser_bridge.mjs');
var frame = await bridge.browser({operation:'capture',tab:实际序号,expected:'实际笔记URL',index:实际图序});
await nodeRepl.emitImage({bytes:Buffer.from(frame.png_base64,'base64'),mimeType:'image/png'});
delete frame.png_base64;
nodeRepl.write(frame); // 删除图片数据后才可输出元数据
```

只把看过后的判断交给`review-image`；捕获成功、翻页成功、图源已加载都不等于目视核验。`memory_worker.mjs`是桥接内部传输，不直接在终端执行或保存其stdout。默认CLI拒绝直接打印图片。`inspect`默认只返回元数据；module的preview只供内存阅读，账本拒绝带preview的page-read输入。

首版已适配小红书主页、笔记文字区作者元数据及Swiper配图；即刻仅主页元数据／公开联系声明存在性。其他页面只保留有限读取信息，不冒称全平台适配。首次动态页面未加载时，允许一次正常后续观察；验证码交用户处理，不调用隐藏接口。

## 独立私密核验（模拟）

本地入口 `scripts/private_verify.py` 使用单独的模拟输入文件。将输入放在 `F:/codex/Temp`，用 `expected` 和 `observed` 放两份对照数据。手机号只比较保留的可见位。转账分别比较带时区的时间、同币种金额和状态。

~~~json
{
  "mode": "simulation",
  "phone": {"expected": "138****0023", "observed": "138****0023"},
  "transfer": {
    "expected": {"time": "2090-03-14T10:00:00+08:00", "amount": "10.00", "status": "completed"},
    "observed": {"time": "2090-03-14T02:00:00Z", "amount": "11.00", "status": "completed"}
  }
}
~~~

~~~powershell
python scripts/private_verify.py --input F:/codex/Temp/核验模拟输入.json --public-report F:/codex/Temp/公开报告.md --output F:/codex/Temp/含模拟核验摘要.md
~~~

`--public-report` 可省略，此时生成单独的核验报告。`--output` 指向 F 盘上的新 Markdown。新增的「私密核验摘要（模拟）」只含核对项和一致或不一致，原公开报告与账本逐字节保留。输入使用掩码手机号、带时区的时间、两位小数字符串金额及固定状态 `pending`、`completed`、`failed` 或 `reversed`。
