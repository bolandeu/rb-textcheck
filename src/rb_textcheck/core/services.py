from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w
from packaging.version import Version

from .errors import CliTooOld, InvalidArguments, InvalidProfile, ProjectNotInitialized, QualityGateFailed
from .models import ProjectConfig
from .version import installed_version

# Derived at import time from this package's own name, so this module never
# needs template substitution: it just works under whatever package_name
# the project was generated with.
_PACKAGE_NAME = __name__.split(".")[0]
PROJECT_DIR_NAME = f".{_PACKAGE_NAME}"
CONFIG_FILE_NAME = "config.toml"


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_DIR_NAME).is_dir():
            return candidate
    return None


def require_project_root(start: Path) -> Path:
    root = find_project_root(start)
    if root is None:
        raise ProjectNotInitialized(str(start))
    return root


def config_path(project_root: Path) -> Path:
    return project_root / PROJECT_DIR_NAME / CONFIG_FILE_NAME


def check_cli_compat(config: ProjectConfig) -> None:
    """Raise CliTooOld if this installed CLI is older than the project's `cli.min_version`.

    A project outlives any single CLI release; this is how it refuses to be
    driven by a CLI that predates a config field or command it relies on.
    Skipped for an uninstalled (bare source) run, which has no version, and
    for a build without a `v*` tag in reach (uv-dynamic-versioning's
    `0.0.0` fallback) — a dev checkout, not a release older than anything.
    """
    installed = installed_version()
    if installed is None or Version(installed).release == (0, 0, 0):
        return
    if Version(installed) < Version(config.cli.min_version):
        raise CliTooOld(installed, config.cli.min_version)


def load_config(project_root: Path, *, check_compat: bool = True) -> ProjectConfig:
    """Load and validate the project config, enforcing `cli.min_version` by default.

    Only `doctor` passes `check_compat=False` — it reports the mismatch as
    one of its checks instead of failing on it.
    """
    data = tomllib.loads(config_path(project_root).read_text())
    config = ProjectConfig.model_validate(data)
    if check_compat:
        check_cli_compat(config)
    return config


def save_config(project_root: Path, config: ProjectConfig) -> None:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(config.model_dump()))


def init_project(project_root: Path, name: str) -> ProjectConfig:
    config = ProjectConfig(name=name)
    save_config(project_root, config)
    return config


# --- textcheck ------------------------------------------------------------------
# Checks import bs4/html5lib/pymorphy3: imported where used, so --help and
# --version don't pay for them.

MD_SUFFIXES = (".md", ".markdown")


def read_text(path: Path) -> str:
    """The text to check from a file; a missing or unreadable file is a bad argument (exit 2)."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise InvalidArguments(f"Cannot read '{path}': {getattr(e, 'strerror', None) or e}") from e


def text_format(source: str, requested: str | None) -> str:
    """--format, else by extension: .md/.markdown -> md, anything else and stdin -> html."""
    from .checks import FORMATS

    if requested is None:
        return "md" if Path(source).suffix.lower() in MD_SUFFIXES else "html"
    if requested not in FORMATS:
        raise InvalidArguments(f"--format must be one of: {', '.join(FORMATS)} (got {requested!r}).")
    return requested


def _load_profile(path: Path | None):
    from .profile import ProfileError, load_profile

    try:
        return load_profile(path)
    except ProfileError as e:
        raise InvalidProfile(str(e)) from e


def run_check(text: str, profile_path: Path | None, fmt: str) -> tuple[dict, QualityGateFailed | None]:
    """Report payload for `check` and the gate problem (None when the gate passed)."""
    from .checks import check

    result = check(text, _load_profile(profile_path), fmt)
    blocking = sum(1 for issue in result.issues if issue.gate)
    return result.as_dict(), (QualityGateFailed(blocking) if blocking else None)


def validate_profile(path: Path) -> dict:
    """`profile validate`: the profile parses, matches the schema, its regexes compile."""
    profile = _load_profile(path)
    return {"profile": str(path), "fingerprint": profile.fingerprint}
