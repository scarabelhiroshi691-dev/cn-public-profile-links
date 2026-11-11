"""Compare masked simulation records and write a result-only Markdown section."""
import argparse
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from profile_links import LedgerError, fields, local_path


TRANSFER_FIELDS = {"time", "amount", "status"}
TRANSFER_STATUSES = {"pending", "completed", "failed", "reversed"}


def masked_phone(value):
    if not isinstance(value, str) or not re.fullmatch(r"1[3-9][0-9]\*{4}[0-9]{4}", value):
        raise ValueError("手机号模拟值须保留前 3 位和后 4 位，中间使用 4 个星号。")
    return value


def transfer(record):
    fields(record, TRANSFER_FIELDS, TRANSFER_FIELDS)
    time, amount, status = record["time"], record["amount"], record["status"]
    if not isinstance(time, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-5][0-9])", time):
        raise ValueError("转账模拟时间须包含秒和时区。")
    if not isinstance(amount, str) or not re.fullmatch(r"[0-9]{1,12}\.[0-9]{2}", amount):
        raise ValueError("转账模拟金额须用两位小数的字符串。")
    if not isinstance(status, str) or status not in TRANSFER_STATUSES:
        raise ValueError("转账模拟状态无效。")
    return datetime.fromisoformat(time), Decimal(amount), status


def compare(data):
    fields(data, {"mode", "phone", "transfer"}, {"mode", "phone", "transfer"})
    if data["mode"] != "simulation":
        raise ValueError("此入口用于模拟核验。")
    phone, records = data["phone"], data["transfer"]
    for pair in (phone, records):
        fields(pair, {"expected", "observed"}, {"expected", "observed"})
    expected = transfer(records["expected"])
    observed = transfer(records["observed"])
    return {
        "手机号可见位": masked_phone(phone["expected"]) == masked_phone(phone["observed"]),
        **{label: a == b for label, a, b in zip(("银证转账时间", "银证转账金额", "银证转账状态"), expected, observed)},
    }


def result_section(data):
    lines = ["## 私密核验摘要（模拟）", "", "| 核对项 | 结果 |", "| --- | --- |"]
    lines.extend(f"| {label} | {'一致' if matched else '不一致'} |" for label, matched in compare(data).items())
    return "\n".join(lines) + "\n"


def write_new(path, content):
    # Both paths are on F; publish the complete report without replacing an existing file.
    folder = local_path("F:/codex/Temp/public-profile-runtime", writing=True)
    folder.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as file:
            temp = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.link(temp, path)
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Local JSON containing masked simulation records")
    parser.add_argument("--public-report", help="Optional existing public Markdown report to copy")
    parser.add_argument("--output", required=True, help="A new Markdown file on F drive")
    args = parser.parse_args()
    source = local_path(args.input)
    output = local_path(args.output, writing=True)
    public = local_path(args.public_report) if args.public_report else None
    if source.suffix.lower() != ".json" or output.suffix.lower() != ".md" or (public and public.suffix.lower() != ".md"):
        raise ValueError("模拟输入使用 JSON，报告使用 Markdown。")
    if public and public.samefile(source):
        raise ValueError("公开报告与模拟输入须分别提供。")
    section = result_section(json.loads(source.read_text(encoding="utf-8-sig")))
    if public:
        report = public.read_text(encoding="utf-8-sig").rstrip()
    else:
        report = "# 核验报告"
    write_new(output, report + "\n\n" + section)
    print("已生成核验报告。")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError):
        # Parse errors and local paths may contain input values.
        print("核验未完成，请检查模拟输入格式、报告路径及输出文件是否已存在。", file=sys.stderr)
        sys.exit(2)
