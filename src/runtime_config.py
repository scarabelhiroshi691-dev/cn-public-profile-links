"""Local runtime configuration shared by Python commands and browser adapters."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]


class ConfigError(ValueError):
    pass


def checked_path(value, *, base=PROJECT, blocked_drives=("E:",)):
    raw = os.path.expandvars(str(value))
    blocked = {x.upper() for x in blocked_drives}
    if PureWindowsPath(raw).drive.upper() in blocked:
        raise ConfigError("Configured drive is frozen; path was not accessed")
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if PureWindowsPath(str(path)).drive.upper() in blocked:
        raise ConfigError("Resolved drive is frozen; target was not accessed")
    return path


def executable(value, *, blocked_drives=("E:",)):
    if not value:
        return None
    if Path(value).is_absolute() or any(c in value for c in "/\\"):
        path = checked_path(value, blocked_drives=blocked_drives)
        return str(path) if path.is_file() else None
    # Skip frozen PATH entries before searching for an executable.
    directories = []
    for item in os.environ.get("PATH", "").split(os.pathsep):
        if not item:
            continue
        try:
            directories.append(str(checked_path(item, blocked_drives=blocked_drives)))
        except ConfigError:
            continue
    result = shutil.which(value, path=os.pathsep.join(directories))
    return str(checked_path(result, blocked_drives=blocked_drives)) if result else None


def _fields(data, allowed, label):
    if not isinstance(data, dict) or set(data) - allowed:
        raise ConfigError(f"Unknown or invalid {label} configuration fields")


def load_config(config_path=None, *, project=PROJECT):
    project = checked_path(project)
    selected = config_path or os.environ.get("PPL_CONFIG")
    path = checked_path(selected or project / ".ppl-config.json", base=project)
    if selected and not path.is_file():
        raise ConfigError("Explicit PPL_CONFIG file is missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except (OSError, ValueError) as error:
        raise ConfigError("Cannot read runtime configuration JSON") from error
    _fields(raw, {"version", "storage", "runtime", "browser"}, "root")
    if raw.get("version", 1) != 1:
        raise ConfigError("Unsupported configuration version")
    storage, runtime, browser = (raw.get(k, {}) for k in ["storage", "runtime", "browser"])
    _fields(storage, {"root", "blocked_drives", "extra_write_roots"}, "storage")
    _fields(runtime, {"node", "cli"}, "runtime")
    _fields(browser, {"session", "profile", "channel", "executable"}, "browser")
    for key in ["node", "cli"]:
        if not isinstance(runtime.get(key, ""), str):
            raise ConfigError("Runtime executable paths must be strings")
    for key in ["session", "profile", "channel", "executable"]:
        if key in browser and not isinstance(browser[key], str):
            raise ConfigError("Browser settings must be strings")
    blocked = storage.get("blocked_drives", ["E:"])
    if not isinstance(blocked, list) or any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z]:", x) for x in blocked):
        raise ConfigError("blocked_drives must contain drive names such as E:")
    extra = storage.get("extra_write_roots", [])
    if not isinstance(extra, list) or any(not isinstance(x, str) or not x for x in extra):
        raise ConfigError("extra_write_roots must be a list of paths")
    if not isinstance(storage.get("root", ".local"), str) or not storage.get("root", ".local"):
        raise ConfigError("storage.root must be a nonempty path")
    if not isinstance(browser.get("profile", ""), str):
        raise ConfigError("browser.profile must be a path string")
    root = checked_path(storage.get("root", ".local"), base=project, blocked_drives=blocked)
    temp = checked_path(root / "tmp", blocked_drives=blocked)
    system_temp = checked_path(tempfile.gettempdir(), blocked_drives=blocked)
    write_roots = [root, system_temp, *[checked_path(x, base=project, blocked_drives=blocked) for x in extra]]
    profile = checked_path(browser.get("profile") or root / "browser-profile", base=project, blocked_drives=blocked)
    if not any(profile.is_relative_to(p) for p in write_roots):
        raise ConfigError("Browser profile must be inside an allowed write root")
    session = browser.get("session") or "ppl-" + hashlib.sha256(str(project).encode()).hexdigest()[:12]
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session):
        raise ConfigError("Invalid browser session name")
    channel = browser.get("channel", "chrome")
    if channel not in {"chrome", "msedge"}:
        raise ConfigError("This release supports installed Chrome or Edge")
    browser_executable = browser.get("executable", "")
    if not isinstance(browser_executable, str):
        raise ConfigError("browser.executable must be a path string")
    if browser_executable:
        chrome = executable(browser_executable, blocked_drives=blocked)
    else:
        candidates = []
        app = "Google/Chrome/Application/chrome.exe" if channel == "chrome" else "Microsoft/Edge/Application/msedge.exe"
        for directory in [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]:
            if directory:
                candidate = checked_path(Path(directory) / app, blocked_drives=blocked)
                if candidate.is_file():
                    candidates.append(str(candidate))
        chrome = candidates[0] if candidates else executable(channel, blocked_drives=blocked)
    node_value = runtime.get("node") or "node"
    if not isinstance(node_value, str) or not isinstance(runtime.get("cli", ""), str):
        raise ConfigError("Runtime executable paths must be strings")
    node = executable(node_value, blocked_drives=blocked)
    cli = checked_path(runtime["cli"], base=project, blocked_drives=blocked) if runtime.get("cli") else None
    if cli is None:
        manifest = project / "node_modules/@playwright/cli/package.json"
        if manifest.is_file():
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            entry = meta.get("bin", {}).get("playwright-cli")
            if not isinstance(entry, str):
                raise ConfigError("Installed Playwright CLI has no executable entry")
            cli = checked_path(manifest.parent / entry, blocked_drives=blocked)
        else:
            cli = checked_path(project / "node_modules/@playwright/cli/playwright-cli.js", blocked_drives=blocked)
    return {"project": str(project), "config_file": str(path), "config_exists": path.exists(),
            "python": sys.executable, "node": node, "cli": str(cli), "root": str(root),
            "data_dir": str(root / "runs"), "temp_dir": str(temp), "cache_dir": str(root / "cache"),
            "profile": str(profile), "session": session, "channel": channel, "browser_executable": chrome,
            "blocked_drives": blocked, "write_roots": [str(p) for p in write_roots]}


@lru_cache(maxsize=1)
def get_config():
    return load_config()


def local_path(value, *, writing=False):
    config = get_config()
    path = checked_path(value, blocked_drives=config["blocked_drives"])
    if writing and not any(path.is_relative_to(Path(root)) for root in config["write_roots"]):
        raise ConfigError("Output path is outside configured write roots")
    return path


def child_env():
    config = get_config()
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PLAYWRIGHT_MCP_", "PLAYWRIGHT_CLI_", "NPM_CONFIG_"))}
    env.update(PPL_PYTHON=sys.executable, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               TEMP=config["temp_dir"], TMP=config["temp_dir"],
               PLAYWRIGHT_BROWSERS_PATH=str(Path(config["cache_dir"]) / "browsers"),
               npm_config_cache=str(Path(config["cache_dir"]) / "npm"),
               npm_config_userconfig=str(Path(config["cache_dir"]) / "npm-user.conf"),
               npm_config_globalconfig=str(Path(config["cache_dir"]) / "npm-global.conf"))
    # Node's browser bridge resolves the same config even when launched from temp.
    if config["config_exists"]:
        env["PPL_CONFIG"] = config["config_file"]
    return env


def browser_command(script):
    config = get_config()
    if not config["node"] or not Path(config["cli"]).is_file():
        raise ConfigError("Browser dependencies missing; run scripts/setup.py install, then doctor")
    Path(config["temp_dir"]).mkdir(parents=True, exist_ok=True)
    return [config["node"], str(PROJECT / "scripts" / script)]


if __name__ == "__main__":
    try:
        print(json.dumps(get_config(), ensure_ascii=False))
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
