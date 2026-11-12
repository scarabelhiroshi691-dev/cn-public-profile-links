"""Install, inspect and launch this repository's configured local runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import venv

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from runtime_config import (ConfigError, checked_path, child_env, executable, get_config,
                            load_config, local_path)


def initialize(runtime_dir=None, node=None):
    path = checked_path(os.environ.get("PPL_CONFIG") or PROJECT / ".ppl-config.json")
    if path.exists():
        if runtime_dir or node:
            raise ConfigError("Configuration exists; edit it explicitly instead of overwriting")
        get_config.cache_clear()
        return get_config()
    raw = json.loads((PROJECT / ".ppl-config.example.json").read_text(encoding="utf-8"))
    if runtime_dir:
        raw["storage"]["root"] = str(checked_path(runtime_dir))
    if node:
        raw["runtime"]["node"] = str(checked_path(node))
    # Validate the candidate before publishing it. No user paths are created on error.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, candidate = tempfile.mkstemp(prefix=".ppl-config-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        load_config(candidate)
        # Exclusive publication keeps a concurrent installer from replacing config.
        os.link(candidate, path)
    finally:
        Path(candidate).unlink(missing_ok=True)
    get_config.cache_clear()
    return get_config()


def prepare_directories(config):
    for name in ["root", "data_dir", "temp_dir", "cache_dir", "profile"]:
        local_path(config[name], writing=True).mkdir(parents=True, exist_ok=True)


def run(args, *, timeout=30, config=None):
    config = config or get_config()
    return subprocess.run(args, cwd=config["temp_dir"], env=child_env(),
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                          **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))


def cli(args, timeout=30):
    config = get_config()
    if not config["node"] or not Path(config["cli"]).is_file():
        raise ConfigError("Local Playwright CLI missing; run setup.py install")
    result = run([config["node"], config["cli"], *args], timeout=timeout)
    if result.returncode:
        # Avoid echoing full browser output or authentication pages.
        raise ConfigError(f"Browser CLI failed ({result.returncode}); run doctor and inspect the visible browser")
    return result.stdout


def install_skill():
    source = PROJECT / "skills/cn-public-profile-links"
    target = checked_path(PROJECT / ".agents/skills/cn-public-profile-links")
    marker = target / ".ppl-install.json"
    if target.exists():
        if not marker.exists():
            raise ConfigError("A local skill already exists; preserve it before installing")
        previous = json.loads(marker.read_text(encoding="utf-8"))
        for name, digest in previous["files"].items():
            p = checked_path(target / name)
            if not p.is_relative_to(target):
                raise ConfigError("Installed skill manifest contains an invalid path")
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                raise ConfigError("Installed skill was edited; preserve your changes before updating")
        for p in source.rglob("*"):
            name = str(p.relative_to(source)).replace("\\", "/")
            if p.is_file() and name not in previous["files"] and (target / name).exists():
                raise ConfigError("A new skill file would overwrite an untracked local file")
    target.mkdir(parents=True, exist_ok=True)
    for p in source.rglob("*"):
        if p.is_file():
            destination = checked_path(target / p.relative_to(source))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, destination)
    entry = target / "SKILL.md"
    body = entry.read_text(encoding="utf-8")
    body += f"\n\n## 本次本地安装\n\n运行仓库位于 `{PROJECT}`。命令从该仓库目录执行，先运行 `python scripts/setup.py doctor`。不得改用历史副本、其他人的缓存路径或浏览器资料。\n"
    entry.write_text(body, encoding="utf-8")
    files = {str(p.relative_to(target)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in target.rglob("*") if p.is_file() and p != marker}
    marker.write_text(json.dumps({"runtime": str(PROJECT), "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def install(runtime_dir=None, node=None):
    config = initialize(runtime_dir, node)
    prepare_directories(config)
    if sys.version_info < (3, 10):
        raise ConfigError("Python 3.10 or newer is required")
    if not config["node"]:
        raise ConfigError("Node.js 20+ missing; install it or configure runtime.node")
    node_version = run([config["node"], "--version"]).stdout.strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", node_version)
    if not match or int(match.group(1)) < 20:
        raise ConfigError("Node.js 20+ is required")
    environment = checked_path(PROJECT / ".venv")
    py = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        venv.EnvBuilder(with_pip=False).create(environment)
    npm = checked_path(Path(config["node"]).parent / "node_modules/npm/bin/npm-cli.js")
    if not npm.is_file():
        raise ConfigError("npm is missing beside Node; install the standard Node.js distribution")
    log = local_path(Path(config["cache_dir"]) / "install.log", writing=True)
    command = [config["node"], str(npm), "ci", "--prefix", str(PROJECT),
               "--ignore-scripts", "--no-audit", "--no-fund", "--cache", str(Path(config["cache_dir"]) / "npm")]
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=PROJECT, env=child_env(), stdout=stream,
                                stderr=subprocess.STDOUT, timeout=240,
                                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    if result.returncode:
        raise ConfigError(f"Dependency install failed; see {log}")
    get_config.cache_clear()
    target = install_skill()
    result = doctor()
    result.update(skill_installed=target, environment_python=str(py))
    return result


def session_section(raw, session):
    match = re.search(r"(?m)^- " + re.escape(session) + r":\s*$", raw)
    return raw[match.end():].split("\n- ", 1)[0] if match else None


def validate_session(section, config):
    if not section or "status: open" not in section:
        raise ConfigError("Configured browser session is not open")
    match = re.search(r"user-data-dir:\s*(.+)", section)
    actual = match.group(1).strip().replace("\\", "/").lower() if match else ""
    expected = config["profile"].replace("\\", "/").lower()
    if actual != expected or "headed: true" not in section:
        raise ConfigError("Existing session uses a different profile or is not visible; no session was changed")


def browser(url):
    from profile_links import public_url
    config = get_config()
    prepare_directories(config)
    url = public_url(url)
    if not config["browser_executable"]:
        raise ConfigError("Configured Chrome/Edge executable is missing; run doctor or set browser.executable")
    section = session_section(cli(["list"]), config["session"])
    if section and "status: open" in section:
        validate_session(section, config)
        cli([f"-s={config['session']}", "tab-new", url])
    else:
        settings = Path(config["temp_dir"]) / "browser-cli.json"
        settings.write_text(json.dumps({"browser": {"browserName": "chromium", "isolated": False,
            "userDataDir": config["profile"], "launchOptions": {"channel": config["channel"], "headless": False,
                "executablePath": config["browser_executable"]}},
            "outputDir": str(Path(config["temp_dir"]) / "browser-output")}), encoding="utf-8")
        cli([f"-s={config['session']}", "open", url, "--headed", "--persistent", "--browser", config["channel"],
             "--profile", config["profile"], "--config", str(settings)], timeout=45)
    validate_session(session_section(cli(["list"]), config["session"]), config)
    return {"ok": True, "session": config["session"], "profile": config["profile"],
            "headed": True, "note": "Authentication and verification must be completed by the user"}


def doctor(check_browser=False):
    config = get_config()
    local_path(config["temp_dir"], writing=True).mkdir(parents=True, exist_ok=True)
    checks = []
    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    add("python", sys.version_info >= (3, 10), sys.version.split()[0])
    if config["node"]:
        version = run([config["node"], "--version"]).stdout.strip()
        match = re.fullmatch(r"v(\d+)\.\d+\.\d+", version)
        add("node", match and int(match.group(1)) >= 20, config["node"] + " " + version)
    else:
        add("node", False, "Install Node.js 20+ or configure runtime.node")
    if config["node"] and Path(config["cli"]).is_file():
        result = run([config["node"], config["cli"], "--version"])
        add("local_playwright_cli", result.returncode == 0, config["cli"] + " " + result.stdout.strip())
    else:
        add("local_playwright_cli", False, config["cli"])
    add("browser_executable", bool(config["browser_executable"]), config["browser_executable"] or "Install Chrome/Edge or configure browser.executable")
    for name in ["root", "data_dir", "temp_dir", "cache_dir", "profile"]:
        try:
            path = local_path(config[name], writing=True)
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path) as f:
                f.write(b"ppl-doctor"); f.flush()
            add(name, True, str(path))
        except OSError as error:
            add(name, False, type(error).__name__)
    skill = PROJECT / ".agents/skills/cn-public-profile-links/SKILL.md"
    add("project_skill", skill.is_file(), str(skill))
    py = PROJECT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    add("project_python", py.is_file(), str(py))
    if check_browser:
        try:
            validate_session(session_section(cli(["list"]), config["session"]), config)
            add("browser_session", True, config["session"])
        except ConfigError as error:
            add("browser_session", False, str(error))
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "config_file": config["config_file"], "browser_checked": check_browser}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ["init", "install"]:
        p = sub.add_parser(name)
        p.add_argument("--runtime-dir")
        p.add_argument("--node")
    p = sub.add_parser("doctor"); p.add_argument("--browser", action="store_true")
    p = sub.add_parser("browser"); p.add_argument("--url", default="https://www.bilibili.com")
    sub.add_parser("config")
    args = parser.parse_args()
    if args.action == "install": result = install(args.runtime_dir, args.node)
    elif args.action == "init": result = initialize(args.runtime_dir, args.node)
    elif args.action == "doctor": result = doctor(args.browser)
    elif args.action == "browser": result = browser(args.url)
    else: result = get_config()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConfigError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
