# 本机执行版（Codex 内试用版）

源码位于本仓库根目录（包含 src、scripts 和 USAGE.md）。默认验证部署位置为 `F:/codex/Projects/public-profile-links`，换目录时使用实际仓库路径，先读取根目录 `USAGE.md` 和 `README.md`。这是当前机器上已实测的执行工具，不代表独立产品或全平台API。不要为了运行它迁移CODEX_HOME、浏览器资料或访问E盘。

## 使用时机

需要持续核验昵称、公开作品或准确主页并保存来源时，建立本轮任务；用账本保存本轮实际观察和待处理项。既有试跑用`legacy`引用，旧的已读／确认结论不会自动升级为本轮结果。多轮恢复时用原任务ID，不重新创建或覆盖历史记录。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python F:/codex/Projects/public-profile-links/scripts/profile_task.py create --label '本轮公开创作者核验' --kind profile --platform '小红书' --value '已取得的完整公开主页URL'
python F:/codex/Projects/public-profile-links/scripts/profile_task.py resume TASK_ID
```

修改数据文件放在 `F:/codex/Temp`任务目录，使用`USAGE.md`中的字段，传入`--data-file`；可以带`--revision`防止旧状态覆盖新状态。程序只做结构和证据门槛检查，不能替代对本人声明、图片准确号、机构签约文字的实际审阅。

## 工具与判断分开

- 浏览器读取前检查共享会话及资料目录，然后查询当前标签；每次读取必须指定准确URL。页面未加载时允许一次后续观察；强制认证交用户处理。不要移除遮罩或调用隐藏接口。
- `inspect`默认只返回元数据。`page-read`核对作者后存档；笔记作者区与侧栏当前登录账号、推荐区分开。带preview的正文不是自动存档材料，账本会拒绝。
- 使用 `scripts/codex_browser_bridge.mjs` 在 Node REPL 调用`capture`，用`nodeRepl.emitImage`显示图片。不要`write`或`text`整个图片结果；不要直接在终端运行内部memory_worker。目视后删除`png_base64`，只保存来源、图序与必要判断。
- `gallery`登记连续图序；未加载图源可为null，仍是pending。只有实际看过并记录判断后才调用`review-image`。`step`、`capture`成功不增加已核验图数。图片打码、小字和重复图分别说明。
- 发现目标变化、错图序、会话关闭或写入失败时停止该项；重开共享浏览器仍用全局脚本和原资料目录，不使用FreshOpen。恢复时重新查标签序号和图序，任务记录不应重置。
- 某端点本轮不能读取时，相关已确认关系转为待复核，历史明确声明保存在relation.history。不要把访问受限理解为历史声明已经证伪。
- `relation`的确认只接受已读端点及明确、已审阅且能定位目标的证据，并须连接到已知根节点；普通合作、同名、转载和摘要不能确认。MCN支持创作者的本人声明及机构的原始反向签约声明，保留证据真实方向，不改写发言者。`business_subject`只记录明确法律主体披露，不等于已完成工商核验。
- 图片准确号证据还须记录`source_image`与`image_index`，并对应账本中同帖同图已目视的记录；只有`reviewed:true`或OCR准确不够。旧alpha缺少来源的确认须补审，不能靠历史标签通过新门槛。
- 微信只记录原始声明来源与用途；不保存联系值，不验证当前有效性。企查查继续按当前用户约定保留登录缺口。

## 当前能力范围

## 稀疏输入与候选恢复

### 公开作品链接起步

公众号文章、B 站直接 BV 视频页和小红书公开笔记使用 `create --kind work` 后执行 `work-run`。公众号的可见「阅读原文」实际跳转在 `next` 和导出中单列为单向观察。按 `next` 核对实际作品发布者，再用 `work-review` 和 `fix-root` 进入现有证据流程。只有第三方提及、对端打不开或公众号缺少指回准确原文的反向证据时保留待核对。多路独立执行后用 `work-compare` 按准确标识对照。命令与字段见项目 `USAGE.md` 的「从一条公开作品链接起步」。

### B 站昵称执行器

输入为 `nickname`＋`B站`／`哔哩哔哩` 时，在同一任务使用 `bilibili-run`，初始页最多保存 10 个 UID 并读 3 个主页。先按 `next` 执行 `bilibili-reverse-start`，再用现有网页检索查给出的原昵称，只沿实际命中的原页及作者入口核对，最多登记 3 个声明来源。用 `bilibili-reverse-result` 写回本人声明、实读站外主页标识和原声明所指 B 站主页。只有已审阅的 GitHub／YouTube 本人原文能指回实读 B 站 UID 时，才确认该方向。若同一原文还列小红书号，在已审阅来源填 `xiaohongshu_id`，按 `next` 定位实际主页，用同一任务的 `entity` 和 `read` 核对主页显示号，再用 `bilibili-reverse-xhs-review` 写入同一发布账号指向小红书的关系。只在实读显示号一致时确认，保留两条原声明方向。只在唯一精确昵称且命中本人反向声明时由审阅动作固定起始账号。反向检索完成后看 `next.nickname_outcome.question`，仍有歧义时只问一条公开 BV 视频链接，使用 `bilibili-clarify` 写入同一任务再继续。原候选、页面和来源继续保留；核对作品作者与实际主页 UID 后由审阅者使用 `fix-root`。入口、字段和中断恢复示例见项目 `USAGE.md` 的「B 站昵称与一条作品线索」。

`fix-root` 后在同一任务再次运行 `bilibili-run`，续读简介与最多 3 条视频，补充视频计入上限。按 `next.materials.reviewable` 打开声明原页与目标核对，用 `bilibili-link-review` 审阅后再沿已确认来源继续。当前站外自动读取支持公开 GitHub 账号和 YouTube `@handle` 频道。报告保留单向来源及待核对项。

### 抖音公开用户卡

输入为 `nickname`＋`抖音` 时，运行 `douyin-run TASK_ID --max-candidates 10 --max-profiles 3`。公开抖音号也可作搜索词。执行器从实际用户搜索卡打开对应主页，分别记搜索范围、落地地址和实读的公开抖音号。搜索结果区未读、候选主页未读、已读但缺归属证据分别保留。若 `next` 给出 `douyin-retry`，在原任务登记重试原因后继续；只在用户实际完成明确的登录或验证码后登记 `authentication_resolved: true`。读取后沿可核实的本人原文进行 `evidence` 和 `relation` 审阅，按声明方向记录。只有确认的账号关联会把候选标为「已确认」。

### 小红书昵称执行器

输入为`nickname`＋`小红书`时，优先创建本轮任务，在首次查询前用`discovery-config`登记先验和总额度，然后`xhs-run TASK_ID --steps 2 --max-candidates 10 --max-profiles 3`。`resume`只查看状态，再次`xhs-run TASK_ID`才继续执行。完整命令及数据文件见项目USAGE的“小红书昵称统一执行入口”。不要对已完成的旧手工查询重放执行器。

执行器复用固定共享Chrome，创建自己的任务标签，检查所有权、实际URL和原样输入，切用户筛选后只采本次渲染卡片，限量读取公开主页元数据。它不自动审阅全部简介／作品，不滚动全量，不按昵称固定根节点或确认关系。`awaiting_review`是候选采集完成，仍须按证据规则审阅。

每个新动作前检查任务停止状态与当前主页总额度；耗尽时保留队列与待恢复意图，`xhs_executor.hold`说明原因。用`discovery-config`调整总额度后可继续初次固定范围内的队列；不要用后续`--max-profiles`参数冒充范围变更。停止须明确`reopen:true`后继续；已经在途的动作结果仍可记录。

`blocked`先查看原因；认证由用户本人在可见浏览器完成后，再用`xhs-retry`写明真实原因及`authentication_resolved:true`，每个中断步骤及查询有单次显式重试上限。普通失败不能用假认证声明解除。当前阻断解除后，历史中断和访问缺口仍保留。崩溃可能留下任务标签；不关闭其他任务、不盲目重放搜索、不换浏览器资料。

报告区分可见条目、去重后候选、过滤数、已读主页和未覆盖。`filtered`是有结果但不可收录，不能写成零结果；只保存过滤数量，不保存联系值。平台明确标注的11位小红书号按平台标识处理，不用于联系方式反查。

`next` 的 `nickname_outcome` 提供结论和范围。复核已读候选后，若 `question` 有值，只使用这一条公开线索问题。`resume` 在 `discovery` 下返回同一结论，Markdown 导出也会显示它。遇到登录或验证，使用访问缺口的处理方式。未完成的查询和用户主动停止的任务不生成澄清问题。

用户给出一条公开作品标题、直接作品页链接或准确小红书号后，用原任务的 `xhs-clarify` 保存（`kind` 分别为 `work_title`、`work_url` 或 `platform_id`），再执行 `xhs-run`。优先读取 `next.clarification`。作品只核对首批及实际作者主页，准确 ID 只与已保存候选精确比较。核对实际来源和准确主页后才执行 `fix-root`。认证或失败按 `xhs-clarify-retry` 的显式恢复流程处理，详见项目 USAGE。保留原昵称输入及原证据记录。

### 已定位账号的公开资料

小红书任务的 `next.materials` 可启动同任务资料整理。每次 `xhs-materials TASK_ID` 读取一个来源，先验证主页标识，再读首批最多 3 条实际作者作品。逐页用 `xhs-materials-review` 提交已复核的非敏感简介、明确职业自述和作品摘要，空页如实记录。页面编号绑定来源及读取时间，原始预览只供当次复核。详细字段及中断恢复见项目 USAGE。

### 已读评论的一层复核

使用 `comments-record` 将本任务起始账号已读笔记下的公开评论登记进账本，再用 `comment-review` 保存语境、用户优先标记和核对过的歌词／文案来源。`next.comments` 给出优先队列。含具体指向的留言可先核对，普通产品问答保留原语境。程序的语句特征只给出初始顺序，Codex 负责审阅。

仅沿原评论可见的署名主页或正文链接进入一层。优先小红书主页可用 `comment-run TASK_ID`，每次自动读取一个。本人回复中的明确大号／小号声明有唯一准确主页链接时进入优先队列，读取正文目标；多个主页链接须通过 `comment-review.target_url` 选择原文中的一个。其他评论默认读取署名主页。保存意图、实际页面和一层记录，已完成项再次调用时跳过。`next.comments.reader` 显示状态。失败后按实际条件变化登记 `comment-read-retry`，真实认证由用户完成后登记 `authentication_resolved: true`，两次未成功后停止重复。

其他原评论明确给出的公开链接用现有浏览器读取、`page-read` 存档，再以 `comment-expand` 绑定原评论和实际落地页，每任务至多 3 个不同目标。访问失败保留未读和恢复条件，关系证据不足保持待核对。落点评论不能继续产生二层扩展。字段和示例入口见项目 USAGE 的「已读评论的线索筛选与一层复核」。

### 其他渠道与关系审阅

创建时使用`--kind nickname --platform 实际平台 --value 公开昵称`，或`--kind work --value 公开作品名`；私人微信值不作输入。随后用`discovery-start`记录选样先验和查询／主页／扩展轮数上限，调用`next TASK_ID`获取动作。

- `public_search`：由助手调用现有公开搜索工具，再用`search-result`保存筛选后的非敏感候选、实际来源与状态。没有结果保存空列表；超时、认证或失败保持对应状态，不写成无结果。查询生成不等于查询已执行。
- `public_search`须按渠道路由：`public_web`走公开网页检索，`xiaohongshu_ui`走正常共享Chrome站内UI。新的小红书昵称任务优先用上节执行器；历史手工`query`要求`platform:小红书`，`terms`为原样公开昵称，不附引号及`site:`。返回待办不是已经搜索。
- `read_profile`／`review_attribution`：读取实际主页与归属依据。只有已读且标识核对的候选，经过`fix-root`记录理由后才能固定为起始账号；原平台尚未确定时可交付候选，不用同名网站顶替。
- 调整查询用`query`；新词须有来自已确认来源的已审阅原文观察。直接链接优先，用`candidate`记录证据与发现路径，不为用完额度重新搜索。未确认候选只做归属核验，不能用其新简介继续扩展。
- 默认8条不同查询、10个主页、2轮扩展；连续两次同分支同渠道无新增候选时停止。`candidate-review`可保留未确认、冲突、排除和只有声明的状态；确认必须走`relation`门槛。报告统计候选、已读和确认分别列出；作者网站不当作社交平台账号。
- 已确认机构关系会从待核归属清单排除，并另作机构关系显示；机构仍不能作为个人账号扩展根节点，不能沿其旗下名单继续增加目标的小号。机构本轮读取失败后须降级并保留历史。
- `stop`记录原因；需继续时显式`reopen:true`。认证交给用户本人处理后才可使用`query-retry`并记录`authentication_resolved:true`，每条中断查询最多显式重试一次，旧尝试保留。不得为解除挂起而假填认证完成；其余独立公开渠道可以继续。

完整数据字段与可执行示例以项目`USAGE.md`为准。公开样本只覆盖所列范围，零命中和未核实目标保留，未重新读取的历史图片、合同和工商关系不自动通过。
