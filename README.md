# cn-public-profile-links

福尔摩斯：公开账号关联。供 Codex 在公开昵称、主页或作品等少量线索下发现候选，核对本人明确公开的账号关联，并导出带来源的 Markdown／JSON 报告。

当前为 **v0.1.0，2026-11-11，Windows 上的 Codex 内试用版**。需要 Codex 浏览和审阅归属，程序负责有界读取、任务状态与账本。确认不了的保留待核对。

## 已支持

| 入口 | 能做什么 |
|---|---|
| 小红书昵称／公开主页／笔记 | 候选发现、补一条作品线索后续办、简介和最多 3 条笔记、公开声明核对。 |
| B 站昵称／UID 主页／BV 视频 | 按 UID 去重、作品澄清、简介和最多 3 条作品、明确公开站外关联。 |
| 抖音公开昵称或抖音号 | 从实际搜索用户卡进入主页，区分未读、已读但缺证据和已确认。 |
| 微信公众号公开文章 | 已知公开作品链接读取，发布方与公开目标分别核验。 |
| 已读小红书评论 | Codex 有界读取并登记；明确账号链接可进入优先队列，只扩展一层，最多 3 个不同落点。 |

本人原文、准确链接／标识和实际目标主页都核对后，才登记明确关联，保留单向或双向的各条证据。仅同名、普通互动和含糊留言不能升级为已确认。

## 安装与环境

本仓库包含技能与运行代码，默认按原 Windows 环境发布。Python 3.10+（维护环境使用 3.12）仅需标准库，Node.js 和 Playwright CLI 用于浏览器读取。当前写入保护要求账本及可配置临时文件位于 F 盘，E 盘拒绝访问。macOS、Linux 和无 F 盘环境未验证。

1. 将仓库放在 F 盘，默认位置 `F:/codex/Projects/public-profile-links`。若使用其他 F 盘目录，下面命令使用实际仓库路径。
2. 将 `skills/cn-public-profile-links` 复制到你的 Codex skills 目录，保留目录名。若已有同名技能，先保留副本并比较再更新。
3. 浏览器适配器目前使用既有共享 Chrome 配置。检查 `scripts/shared_browser.mjs` 顶部 NODE、CLI、SESSION、PROFILE、TEMP，确保实际 Node 和 Playwright CLI 路径存在；这里的 npm 缓存路径来自维护机，其他机器必须调整。Python 浏览器调用默认 Node 为 `C:/Program Files/nodejs/node.exe`。不要直接照搬失效的缓存路径。
4. 维护环境复用 `D:/Codex/BrowserProfiles/CodexAutomation`，会话名 `codex-shared-browser`，通过已有 `D:/Codex/Tools/Browser/Start-CodexBrowser.ps1` 启动。启动脚本和浏览器资料不随仓库分发。其他机器须先建立符合自身规则的可见持久会话，再对应调整适配器的资料校验；不要读取或复制主浏览器密码／Cookie。
5. 登录、验证码和双重验证由用户本人处理。不要为试跑绕过平台认证。

无需先打开浏览器即可运行帮助与离线检查。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='F:/codex/Temp/public-profile-runtime'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
python -B scripts/profile_task.py --help
python -B -m unittest discover -s tests -p 'test_*.py' -q
$nodeTests = (Get-ChildItem -LiteralPath tests -Filter '*.test.mjs').FullName
node --test $nodeTests
```

## 日常使用

在 Codex 里说：

> 用 $cn-public-profile-links 查小红书昵称「示例昵称」。先查候选，重名时只问我一条公开线索。定位后读简介和最多 3 条笔记，沿明确公开声明只扩展一层。最后导出 Markdown 和 JSON，分开写已确认、待核对和实际未读范围，每项附来源。

详细字段、恢复与命令见 [USAGE.md](USAGE.md)，证据门槛见 [证据与报告规则](skills/cn-public-profile-links/references/evidence-and-report.md)。平台登录状态、查询时间和公开资料会影响结果，不保证找到站外关联。

## 仓库内容与数据边界

`skills/` 是可安装的技能，`src/` 与 `scripts/` 是运行工具，`tests/` 为离线检查，`test-runs/synthetic-*.json` 为人工合成测试夹具。`scripts/private_verify.py` 仅支持脱敏模拟字段对照，不是手机号或金融信息找人工具。

真实案例、调查账本、截图、评论采集记录、私人线索、浏览器资料和凭据均未包含。运行后产生的 `runs/`、`eval/`、缓存和日志默认忽略，不要提交用户数据。公开来源也不应被用来拼接敏感个人画像、揭示匿名身份或推断私人关系。

## 当前限制

有限翻页、公众号短长链和仓库跳转的专项继续暂缓。真实登录／验证码后的恢复仍待正常使用实际触发验证，受控测试通过不能替代现场验收。本版没有独立后台采集和全平台搜索 API。

发布范围、检查结果见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。
