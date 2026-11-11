"""CLI for the local evidence ledger; Python standard library only."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from profile_links import Store, OPERATIONS, LedgerError, local_path, public_url, progress, report, PROJECT
from discovery import OPERATIONS as DISCOVERY_OPERATIONS, next_actions
from douyin_runtime import OPERATIONS as DOUYIN_OPERATIONS, run as run_douyin
from comment_leads import OPERATIONS as COMMENT_OPERATIONS
from comment_runtime import OPERATIONS as COMMENT_READER_OPERATIONS, run as run_comments
from xhs_runtime import OPERATIONS as XHS_OPERATIONS, run as run_xhs, call_browser
from xhs_materials import OPERATIONS as MATERIAL_OPERATIONS, run as run_materials
from bilibili_runtime import OPERATIONS as BILIBILI_OPERATIONS, run as run_bilibili
from work_runtime import OPERATIONS as WORK_OPERATIONS, compare as compare_work, run as run_work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create")
    new.add_argument("--label", required=True)
    new.add_argument("--kind", choices=["profile", "nickname", "work"], required=True)
    new.add_argument("--value", required=True)
    new.add_argument("--platform", default="unknown")
    for name in ("show", "resume", "next", "export", "recover-lock"):
        p = sub.add_parser(name)
        p.add_argument("task_id")
    read = sub.add_parser("read", help="Read a known public page using the shared Chrome and save metadata")
    read.add_argument("task_id")
    read.add_argument("--entity", required=True)
    read.add_argument("--tab", required=True, type=int)
    read.add_argument("--expect", required=True, help="Exact observed page URL, not a guessed account path")
    xhs = sub.add_parser('xhs-run', help='Run/resume bounded normal Xiaohongshu UI steps')
    xhs.add_argument('task_id')
    xhs.add_argument('--steps',type=int,default=20)
    xhs.add_argument('--max-candidates',type=int,default=10)
    xhs.add_argument('--max-profiles',type=int,default=3)
    materials = sub.add_parser('xhs-materials', help='Read one bounded source of the reviewed Xiaohongshu account')
    materials.add_argument('task_id')
    bili = sub.add_parser('bilibili-run', help='Run or resume Bilibili discovery or the reviewed account’s public sources')
    bili.add_argument('task_id')
    bili.add_argument('--steps', type=int, default=10)
    douyin = sub.add_parser("douyin-run", help="Read public Douyin profiles from actual user search cards")
    douyin.add_argument("task_id")
    douyin.add_argument("--max-candidates", type=int, default=10)
    douyin.add_argument("--max-profiles", type=int, default=3)
    comments = sub.add_parser("comment-run", help="Read or resume one saved priority comment profile target")
    comments.add_argument("task_id")
    work = sub.add_parser("work-run", help="Read a public work through the evidence ledger")
    work.add_argument("task_id")
    work.add_argument("--url", help="Another observed public work in this task")
    work.add_argument("--source", help="Source from which the additional work was discovered")
    work.add_argument("--retry", action="store_true")
    compare = sub.add_parser("work-compare", help="Compare verified works and accounts across separate tasks")
    compare.add_argument("task_ids", nargs="+")
    operations = OPERATIONS | DISCOVERY_OPERATIONS | XHS_OPERATIONS | MATERIAL_OPERATIONS | BILIBILI_OPERATIONS | WORK_OPERATIONS | DOUYIN_OPERATIONS | COMMENT_OPERATIONS | COMMENT_READER_OPERATIONS
    for name in operations:
        p = sub.add_parser(name)
        p.add_argument("task_id")
        p.add_argument("--data-file", required=True, help="Explicitly reviewed fields, never raw page dumps")
        p.add_argument("--revision", type=int)
    args = parser.parse_args()
    store = Store(args.state_root)
    if args.command == "create":
        result = progress(store.create(args.label, args.kind, args.value, args.platform))
    elif args.command == 'xhs-run':
        result=progress(run_xhs(store,args.task_id,args.steps,args.max_candidates,args.max_profiles))
    elif args.command == "bilibili-run":
        result = progress(run_bilibili(store, args.task_id, args.steps))
    elif args.command == "douyin-run":
        result = progress(run_douyin(store, args.task_id, args.max_candidates, args.max_profiles))
    elif args.command == "comment-run":
        result = progress(run_comments(store, args.task_id))
    elif args.command == "work-run":
        result = progress(run_work(store, args.task_id, args.url, args.source, args.retry))
    elif args.command == "work-compare":
        result = compare_work([store.load(task_id) for task_id in args.task_ids])
    elif args.command == "xhs-materials":
        result = run_materials(store, args.task_id, call_browser)
    elif args.command == "read":
        expected = public_url(args.expect)
        before = store.load(args.task_id)
        if args.entity not in before["entities"]:
            raise LedgerError("Unknown entity")
        temp = local_path('F:/codex/Temp/public-profile-runtime', writing=True)
        temp.mkdir(parents=True, exist_ok=True)
        command = ['C:/Program Files/nodejs/node.exe', str(PROJECT/'scripts/shared_browser.mjs'), 'inspect',
                   '--tab', str(args.tab), '--expect', expected]
        try:
            proc = subprocess.run(command, cwd=PROJECT, env={**os.environ, 'TEMP':str(temp), 'TMP':str(temp)},
                                  capture_output=True, text=True, encoding='utf-8', timeout=35)
            if proc.returncode:
                raise LedgerError(json.loads(proc.stderr).get('error', 'Browser read failed'))
            reading = json.loads(proc.stdout)
            task, key = store.update(args.task_id, 'reading', {'entity_id':args.entity, 'reading':reading}, before['revision'])
            result = {'page_id':key, **progress(task)}
        except (LedgerError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            # Keep prior observations and the expected URL; do not adopt the wrong page's identity.
            store.update(args.task_id, 'queue', {'url':expected, 'purpose':'页面元数据及作者核对', 'status':'failed',
                                               'note':str(error)[:500]})
            raise LedgerError(str(error)) from error
    elif args.command == "recover-lock":
        store.recover_lock(args.task_id)
        result = {"lock_recovered": args.task_id}
    elif args.command in operations:
        data = json.loads(local_path(args.data_file).read_text(encoding="utf-8-sig"))
        task, key = store.update(args.task_id, args.command, data, args.revision)
        result = {"result_id": key, **progress(task)}
    else:
        task = store.load(args.task_id)
        if args.command == "export":
            folder = local_path(store.directory / "reports" / args.task_id, writing=True)
            folder.mkdir(parents=True, exist_ok=True)
            # Each revision has its own export; task state remains the durable source.
            name = f"r{task['revision']}"
            (folder / f"{name}.json").write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (folder / f"{name}.md").write_text(report(task), encoding="utf-8")
            result = {"json": str(folder / f"{name}.json"), "markdown": str(folder / f"{name}.md")}
        else:
            result = task if args.command == "show" else next_actions(task) if args.command == "next" else progress(task)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (LedgerError, OSError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
