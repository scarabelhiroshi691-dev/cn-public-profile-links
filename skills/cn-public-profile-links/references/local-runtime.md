# 本地执行工具

运行代码位于本仓库根目录，包含 README.md、USAGE.md、scripts 和 src。技能由安装器复制到仓库的 `.agents/skills/cn-public-profile-links`，安装后的 SKILL.md 末尾绑定实际仓库目录。先定位该目录，不要使用维护机的旧路径或 npm 缓存。

## 首次使用

在运行仓库根目录执行：

```powershell
python -X utf8 -B scripts/setup.py install
.venv/Scripts/python.exe -X utf8 -B scripts/setup.py doctor
.venv/Scripts/python.exe -X utf8 -B scripts/setup.py browser --url https://www.bilibili.com
.venv/Scripts/python.exe -X utf8 -B scripts/setup.py doctor --browser
```

默认也可用根目录 Start-Browser.py；PowerShell允许本地脚本时，可选用 Setup.ps1 和 Start-Browser.ps1。安装器仅配置仓库本身，创建项目级技能、新虚拟环境和本项目固定版本 Playwright CLI。Python、Node.js 和 Chrome／Edge 需要系统已安装。安装器不会读取或迁移 CODEX_HOME、主浏览器资料、账号密码或 Cookie。

自检失败时说明具体缺项，不继续声称已经浏览。浏览器要求用户本人登录或验证码时保留原任务，用户完成后按对应重试命令恢复。

## 配置和目录

本地 `.ppl-config.json` 或 PPL_CONFIG 指定的 JSON 控制运行目录、Node／CLI 位置、浏览器会话和资料。空 executable 路径自动查找本机安装及本项目依赖。默认状态、临时文件、缓存和独立浏览器资料均在仓库 `.local`，其他输出必须位于配置允许的根目录。

冻结盘和用户存储要求优先。错误会话或错误资料目录时停止，不关闭或接管别的浏览器。已有匹配会话仅新建标签。安装信息只证明本机依赖齐全，真实读取与关系审阅仍需另行完成。

## 任务操作

```powershell
.venv/Scripts/python.exe -X utf8 -B scripts/profile_task.py create --label '公开账号核对' --kind nickname --platform '小红书' --value '公开昵称'
.venv/Scripts/python.exe -X utf8 -B scripts/profile_task.py xhs-run TASK_ID
.venv/Scripts/python.exe -X utf8 -B scripts/profile_task.py next TASK_ID
.venv/Scripts/python.exe -X utf8 -B scripts/profile_task.py resume TASK_ID
.venv/Scripts/python.exe -X utf8 -B scripts/profile_task.py export TASK_ID
```

默认账本为配置运行目录下的 runs，Markdown／JSON 存入账本的 reports。所有修改采用数据文件，完整字段见仓库 USAGE.md。恢复沿用原任务和相同 state-root，不能重建任务掩盖中断或换人。

- 小红书用 xhs-run 进行有界昵称发现，xhs-clarify 保存一条公开线索。已读候选和线索经 Codex 审阅后以 fix-root 固定账号，xhs-materials 每次读一个公开来源，最多 3 条笔记，xhs-materials-review 保存精简资料。
- B站用 bilibili-run，以 UID 去重。bilibili-clarify 用一条实际 BV 作品核对作者；固定后在原任务续读简介、最多 3 条作品和明确站外声明，审阅后再关联。
- 抖音用 douyin-run 从实际用户卡进入主页。未读、已读缺证据和已确认分开。其他公开入口由 Codex 使用已有公开检索和浏览器核对，不声称存在全平台 API。
- 公开作品入口用 work-run，先核对实际作者和账号，再经 work-review 审阅。只有第三方提及或对端打不开时保留待核对。
- 公开评论由 Codex 有界实读，comments-record 登记原笔记和评论 ID。comment-review 安排优先级，comment-run 每次只读一个已保存的直接小红书主页。本人回复含唯一准确主页链接时读正文目标；多个链接先选定原文中的一个。每任务最多 3 个不同落点，只扩展一层。读取本身不确认关系。
- 证据以 evidence 记录真实原文、准确标识和方向，经审阅才用 relation 确认。账号自述、项目链接、未知关系及访问缺口分别保留。

程序检查结构与来源门槛，归属仍由 Codex 审阅。不会按同名、头像或普通评论自动合并。有限翻页和公众号短长链／仓库跳转专项仍暂缓。真实认证恢复与异机运行的验证状态以版本说明为准，离线通过不能冒充现场成功。
