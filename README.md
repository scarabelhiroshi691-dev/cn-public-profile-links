# cn-public-profile-links

福尔摩斯：公开账号关联。给 Codex 一条公开昵称、主页或作品线索，发现候选，按本人明确公开声明核对账号，导出带来源的 Markdown／JSON。当前为 **v0.2.0 Windows／Codex 内试用版**。

## 首次安装

系统先准备 **Python 3.10+、Node.js 20+、Chrome 或 Edge**。下载完整仓库并解压到你选定的可写目录，在该目录打开 PowerShell。无需维护者的电脑、账号、浏览器资料或 npm 缓存。

```powershell
python -X utf8 -B scripts/setup.py install
```

安装器会创建本仓库 `.venv`、安装 package-lock.json 锁定的本项目浏览器工具、生成本地配置，并将技能安装到本项目 `.agents/skills/cn-public-profile-links`。不修改全局 Codex 配置、其他项目技能或主浏览器资料。Python 标准库已够用，无需 pip 安装业务依赖。首次安装需要访问 npm 下载锁定依赖。

可替代使用 `./Setup.ps1 -Action install`。已有本地配置会保留；安装过的项目技能若被手工编辑，安装器会停止并要求你先保留修改。

## 自检与启动

```powershell
# 离线自检，缺项返回非零退出码
.venv/Scripts/python.exe -X utf8 -B scripts/setup.py doctor

# 启动本项目的可见持久浏览器
python -X utf8 -B Start-Browser.py --url https://www.bilibili.com

# 检查实际会话、资料目录和可见状态
.venv/Scripts/python.exe -X utf8 -B scripts/setup.py doctor --browser
```

也可用 `.venv/Scripts/python.exe -X utf8 -B scripts/setup.py browser --url https://www.bilibili.com`。PowerShell允许执行本地脚本时，另有 `./Start-Browser.ps1 -Url 实际URL`；若脚本被系统策略阻止，直接使用上面的Python入口，无需改变执行策略。已有匹配会话时只新增标签，不关闭其他标签；同名会话若资料或可见状态不符就停止。需要网站登录、验证码和双重验证时，由用户本人在此浏览器完成。

自检通过只说明安装及所选检查就绪，实际网站访问和证据核对另行进行。

## 在 Codex 里使用

用 Codex 打开这个仓库目录。项目技能会被识别；未出现时重启 Codex。然后说：

> 使用 `$cn-public-profile-links` 查小红书昵称「示例昵称」。先查候选，重名时只问我一条公开线索。定位后读简介和最多3条笔记，沿明确公开声明只扩展一层。最后导出 Markdown 和 JSON，把已确认、待核对及未读范围分开，每项附来源。

安装到这个项目的技能绑定实际运行目录。只复制 SKILL.md 不会同时安装运行工具；完整仓库、依赖和浏览器需按上面步骤准备。[Codex 官方技能说明](https://learn.chatgpt.com/docs/build-skills)

## 可配置内容

首次安装生成 `.ppl-config.json`，示例是 [.ppl-config.example.json](.ppl-config.example.json)。`PPL_CONFIG` 可指定另一个配置文件；相对路径以本仓库为基准。修改后重启当前命令或浏览器会话，不会静默迁移原数据。

| 设置 | 默认行为 |
|---|---|
| `storage.root` | 仓库 `.local`，其下保存 runs、tmp、cache 和浏览器资料。可改为其他获准目录；首次安装也可传 `--runtime-dir 实际目录`。 |
| `storage.blocked_drives` | 默认拒绝 E 盘。按设备实际规则设置，任何全局冻结要求优先，不为绕过失败而放宽。 |
| `storage.extra_write_roots` | 额外获准输出根目录。默认允许运行根和系统临时目录，其他地方不能写账本或报告。 |
| `runtime.node` | 空值从本机 PATH 自动找 Node。也可明确填写可执行文件。 |
| `runtime.cli` | 空值读取本项目 node_modules 中锁定依赖的真实入口，不使用维护机的缓存路径。 |
| `browser.session` | 空值按仓库路径生成独立会话名；可明确指定。 |
| `browser.profile` | 空值使用运行根下的 browser-profile；必须位于获准输出根内。 |
| `browser.channel` / `browser.executable` | 使用已安装 Chrome／Edge；非标准位置可指定实际可执行文件。 |

可用 `python -X utf8 -B scripts/setup.py config` 查看实际解析结果。脚本之间自动传递同一配置和 Python 位置。运行目录、配置、虚拟环境、依赖、项目技能副本和浏览器资料已加入忽略清单。

## 功能范围

| 公开入口 | 当前能力 |
|---|---|
| 小红书昵称／主页／笔记 | 有界候选发现、一条线索原任务续办、简介和最多3条笔记、明确账号声明。 |
| B站昵称／UID主页／BV视频 | 按UID去重、作品澄清、简介和最多3条作品、明确站外声明。 |
| 抖音昵称／公开抖音号 | 实际用户卡到主页，区分未读、已读缺证据和已确认。 |
| 公众号公开文章 | 已知作品链接读取，发布方和对端分别核验。 |
| 已读小红书评论 | Codex有界采集并登记；优先目标一次一个，只扩展一层，每任务最多3个不同落点。 |

候选不等于本人，读过主页不等于确认关系。本人原文、准确标识／链接和实际目标均核对并经Codex审阅后才确认，声明方向保留。普通互动、同名、头像相似不用于推断私人关系。完整操作字段见 [USAGE.md](USAGE.md)。

## 运行检查

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP=(Resolve-Path .local/tmp).Path
$env:TMP=$env:TEMP
.venv/Scripts/python.exe -B -m unittest discover -s tests -p 'test_*.py' -q
$nodeTests=(Get-ChildItem -LiteralPath tests -Filter '*.test.mjs').FullName
node --test $nodeTests
```

`test-runs/synthetic-*.json` 是合成夹具。真实案例、调查账本、截图、评论采集记录、私人线索、浏览器资料及凭据不随仓库分发。私密核验入口仅支持脱敏模拟字段对照，不提供手机号找人。

Windows是本版目标环境；macOS／Linux和另一台实体电脑未验证。有限翻页、公众号短长链和仓库跳转专项继续暂缓，真实平台认证恢复仍按实际触发记录。安装、自检、浏览器实跑的验证结果分开列在 [RELEASE_NOTES.md](RELEASE_NOTES.md) 和 RELEASE_CHECKS.json。
