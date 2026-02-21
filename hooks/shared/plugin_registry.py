"""Plugin registry for the Torus framework.

Scans ~/.claude/plugins/ and marketplace directories to enumerate available
plugins, resolving metadata, enabled status, categories, and dependencies.

Cache path: /dev/shm/claude-hooks/plugin_registry.json  (ramdisk, fast writes)
Fallback:   ~/.claude/hooks/.plugin_registry_cache.json  (disk)

Design constraints:
- Fail-open: all public functions swallow exceptions; never breaks gate enforcement.
- Read-only: this module never modifies plugin files or settings.json.
- Idempotent: calling scan_plugins() multiple times yields the same result.

Plugin metadata schema (all fields are optional in source files):
    name         str   Plugin identifier (e.g. "code-review")
    version      str   Semver string, defaults to "0.0.0"
    description  str   Human-readable summary
    category     str   One of KNOWN_CATEGORIES; inferred from name/description if absent
    enabled      bool  True when listed in settings.json enabledPlugins
    dependencies list  Plugin names this plugin requires
    source       str   "marketplace:<marketplace_name>" | "local"
    path         str   Absolute directory path for this plugin
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_CATEGORIES: tuple[str, ...] = (
    "quality",
    "security",
    "development",
    "infrastructure",
    "monitoring",
)

# Category inference: keyword -> category (checked against name + description)
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "quality": [
        "review", "simplif", "lint", "format", "style", "quality", "clean",
        "output-style", "explanatory", "learning-output",
    ],
    "security": [
        "security", "vulnerab", "audit", "compliance", "policy", "block",
        "guardian", "secret",
    ],
    "development": [
        "lsp", "dev", "feature", "setup", "skill", "agent-sdk", "plugin-dev",
        "hook", "commit", "pr-review", "code", "typescript", "pyright", "rust",
        "gopls", "clangd", "lua", "php", "swift", "kotlin", "csharp", "jdtls",
        "playground", "ralph",
    ],
    "infrastructure": [
        "infra", "deploy", "ci", "pipeline", "docker", "cloud", "monitor",
        "backup", "restore", "setup",
    ],
    "monitoring": [
        "monitor", "metric", "alert", "health", "telemetry", "dashboard",
        "observ",
    ],
}

# Cache paths (mirrors metrics_collector pattern)
_CACHE_RAMDISK_DIR = "/dev/shm/claude-hooks"
_CACHE_RAMDISK_PATH = os.path.join(_CACHE_RAMDISK_DIR, "plugin_registry.json")
_CACHE_DISK_FALLBACK = os.path.join(
    os.path.expanduser("~"), ".claude", "hooks", ".plugin_registry_cache.json"
)

# Plugin directory roots
_PLUGINS_BASE = os.path.join(os.path.expanduser("~"), ".claude", "plugins")
_MARKETPLACES_DIR = os.path.join(_PLUGINS_BASE, "marketplaces")
_SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")

# Staleness threshold for the on-disk cache (seconds)
_CACHE_MAX_AGE = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _infer_category(name: str, description: str) -> str:
    """Return the best-matching category for a plugin given its name and description.

    Scans lowercased name+description against _CATEGORY_KEYWORDS.
    Returns "development" as the default if no keyword matches.
    """
    haystack = (name + " " + description).lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in haystack:
                return category
    return "development"


def _read_settings_enabled() -> dict[str, bool]:
    """Return the enabledPlugins mapping from settings.json.

    Keys are plugin identifiers (e.g. "code-review@claude-plugins-official").
    Returns an empty dict if the file cannot be read or parsed.
    """
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("enabledPlugins", {})
        if isinstance(raw, dict):
            return {k: bool(v) for k, v in raw.items()}
        return {}
    except Exception:
        return {}


def _read_plugin_json(plugin_dir: str) -> dict[str, Any]:
    """Read and return a plugin's metadata from its .claude-plugin/plugin.json.

    Falls back to an empty dict on any error.
    """
    candidate = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
    try:
        with open(candidate, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _build_plugin_record(
    plugin_dir: str,
    source: str,
    marketplace: str,
    enabled_map: dict[str, bool],
) -> dict[str, Any] | None:
    """Build a normalised plugin record from a plugin directory.

    Returns None if the directory does not look like a valid plugin.

    Args:
        plugin_dir:   Absolute path to the plugin directory.
        source:       "marketplace:<name>" or "local".
        marketplace:  Marketplace name (empty string for local plugins).
        enabled_map:  Loaded enabled-plugin mapping from settings.json.

    Returns:
        Normalised plugin record dict or None.
    """
    if not os.path.isdir(plugin_dir):
        return None

    raw = _read_plugin_json(plugin_dir)

    # Derive the canonical plugin name: prefer JSON field, fall back to dir basename
    name: str = raw.get("name") or os.path.basename(plugin_dir)
    if not name:
        return None

    version: str = str(raw.get("version") or "0.0.0")
    description: str = str(raw.get("description") or "")
    dependencies: list[str] = list(raw.get("dependencies") or [])

    # Category: prefer explicit field, then infer
    raw_category = raw.get("category", "")
    if raw_category in KNOWN_CATEGORIES:
        category = raw_category
    else:
        category = _infer_category(name, description)

    # Resolve enabled status from settings.json
    # The key format is "<name>@<marketplace>" for marketplace plugins
    enabled = False
    if marketplace:
        key = f"{name}@{marketplace}"
        enabled = enabled_map.get(key, False)
    else:
        # Local plugins: try bare name
        enabled = enabled_map.get(name, False)

    return {
        "name": name,
        "version": version,
        "description": description,
        "category": category,
        "enabled": enabled,
        "dependencies": dependencies,
        "source": source,
        "path": plugin_dir,
    }


def _scan_marketplace(marketplace_name: str, enabled_map: dict[str, bool]) -> list[dict]:
    """Scan a single marketplace directory and return all plugin records."""
    market_plugins_dir = os.path.join(_MARKETPLACES_DIR, marketplace_name, "plugins")
    if not os.path.isdir(market_plugins_dir):
        return []

    records: list[dict] = []
    try:
        for entry in os.scandir(market_plugins_dir):
            if not entry.is_dir(follow_symlinks=False):
                continue
            record = _build_plugin_record(
                plugin_dir=entry.path,
                source=f"marketplace:{marketplace_name}",
                marketplace=marketplace_name,
                enabled_map=enabled_map,
            )
            if record is not None:
                records.append(record)
    except OSError:
        pass
    return records


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path() -> str:
    """Return the active cache file path (ramdisk or disk fallback)."""
    if os.path.isdir(_CACHE_RAMDISK_DIR):
        try:
            test = os.path.join(_CACHE_RAMDISK_DIR, ".write_test")
            with open(test, "w") as fh:
                fh.write("ok")
            os.remove(test)
            return _CACHE_RAMDISK_PATH
        except OSError:
            pass
    return _CACHE_DISK_FALLBACK


def _write_cache(plugins: list[dict]) -> None:
    """Persist the plugin list to the cache file (fail-open)."""
    try:
        path = _cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "timestamp": time.time(),
            "plugins": plugins,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def _read_cache() -> list[dict] | None:
    """Return cached plugin list if it exists and is fresh, else None."""
    try:
        path = _cache_path()
        if not os.path.exists(path):
            return None
        mtime = os.path.getmtime(path)
        if time.time() - mtime > _CACHE_MAX_AGE:
            return None
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        plugins = payload.get("plugins")
        if isinstance(plugins, list):
            return plugins
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_plugins(base_path: str = _PLUGINS_BASE, *, use_cache: bool = True) -> list[dict]:
    """Scan the plugins directory and marketplaces, returning all plugin records.

    Results are cached to the ramdisk (or disk fallback) for 5 minutes.
    Pass use_cache=False to force a fresh scan.

    Args:
        base_path:  Root plugins directory (default: ~/.claude/plugins/).
        use_cache:  Return cached results if available and fresh.

    Returns:
        List of normalised plugin record dicts.  Each record contains:
            name, version, description, category, enabled, dependencies,
            source, path.
    """
    if use_cache:
        cached = _read_cache()
        if cached is not None:
            return cached

    enabled_map = _read_settings_enabled()
    plugins: list[dict] = []

    # 1. Marketplace plugins
    marketplaces_root = os.path.join(base_path, "marketplaces")
    if os.path.isdir(marketplaces_root):
        try:
            for entry in os.scandir(marketplaces_root):
                if entry.is_dir(follow_symlinks=False):
                    plugins.extend(
                        _scan_marketplace(entry.name, enabled_map)
                    )
        except OSError:
            pass

    # 2. Locally installed plugins (cache/<marketplace>/<name>/<version>)
    cache_root = os.path.join(base_path, "cache")
    if os.path.isdir(cache_root):
        try:
            for mkt_entry in os.scandir(cache_root):
                if not mkt_entry.is_dir():
                    continue
                for plugin_entry in os.scandir(mkt_entry.path):
                    if not plugin_entry.is_dir():
                        continue
                    # Inside: version directories; scan each
                    for ver_entry in os.scandir(plugin_entry.path):
                        if not ver_entry.is_dir():
                            continue
                        record = _build_plugin_record(
                            plugin_dir=ver_entry.path,
                            source=f"marketplace:{mkt_entry.name}",
                            marketplace=mkt_entry.name,
                            enabled_map=enabled_map,
                        )
                        if record is not None:
                            # Avoid duplicates with marketplace scan; mark as installed
                            record["installed"] = True
        except OSError:
            pass

    # De-duplicate: marketplace source is canonical; keep first occurrence per name+source
    seen: set[str] = set()
    deduped: list[dict] = []
    for p in plugins:
        key = f"{p['name']}|{p['source']}"
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    _write_cache(deduped)
    return deduped


def get_plugin(name: str, base_path: str = _PLUGINS_BASE) -> dict | None:
    """Return the plugin record for the given name, or None if not found.

    Performs a case-insensitive match on the plugin's name field.

    Args:
        name:       Plugin name to look up (e.g. "code-review").
        base_path:  Root plugins directory (default: ~/.claude/plugins/).

    Returns:
        Plugin record dict or None.
    """
    name_lower = name.lower()
    for plugin in scan_plugins(base_path):
        if plugin["name"].lower() == name_lower:
            return plugin
    return None


def is_enabled(name: str, base_path: str = _PLUGINS_BASE) -> bool:
    """Return True if the named plugin is currently enabled in settings.json.

    Args:
        name:       Plugin name (e.g. "code-review").
        base_path:  Root plugins directory.

    Returns:
        True if enabled, False if disabled or not found.
    """
    plugin = get_plugin(name, base_path)
    if plugin is None:
        return False
    return bool(plugin.get("enabled", False))


def get_by_category(category: str, base_path: str = _PLUGINS_BASE) -> list[dict]:
    """Return all plugins in the specified category.

    Args:
        category:   One of KNOWN_CATEGORIES (case-insensitive).
        base_path:  Root plugins directory.

    Returns:
        List of plugin records matching the category.  Empty list if none found.
    """
    cat_lower = category.lower()
    return [p for p in scan_plugins(base_path) if p["category"].lower() == cat_lower]


def validate_plugin(path: str) -> tuple[bool, list[str]]:
    """Check whether a plugin directory is structurally valid.

    Validation rules:
    1. path must be an existing directory.
    2. path/.claude-plugin/plugin.json must exist and be valid JSON.
    3. plugin.json must contain a non-empty "name" field.
    4. If "version" is present it must be a non-empty string.
    5. If "dependencies" is present it must be a list.
    6. If "category" is present it must be one of KNOWN_CATEGORIES.

    Args:
        path:  Absolute path to the plugin directory.

    Returns:
        (valid, errors) — valid is True only when errors is empty.
    """
    errors: list[str] = []

    if not path:
        errors.append("path must not be empty")
        return False, errors

    if not os.path.isdir(path):
        errors.append(f"path does not exist or is not a directory: {path}")
        return False, errors

    manifest_path = os.path.join(path, ".claude-plugin", "plugin.json")
    if not os.path.isfile(manifest_path):
        errors.append(f"missing manifest: {manifest_path}")
        return False, errors

    try:
        with open(manifest_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        errors.append(f"plugin.json is not valid JSON: {exc}")
        return False, errors
    except OSError as exc:
        errors.append(f"cannot read plugin.json: {exc}")
        return False, errors

    if not isinstance(data, dict):
        errors.append("plugin.json must be a JSON object")
        return False, errors

    name_val = data.get("name")
    if not name_val or not isinstance(name_val, str) or not name_val.strip():
        errors.append("plugin.json must have a non-empty 'name' string field")

    version_val = data.get("version")
    if version_val is not None:
        if not isinstance(version_val, str) or not version_val.strip():
            errors.append("'version' must be a non-empty string when present")

    deps_val = data.get("dependencies")
    if deps_val is not None and not isinstance(deps_val, list):
        errors.append("'dependencies' must be a list when present")

    category_val = data.get("category")
    if category_val is not None and category_val not in KNOWN_CATEGORIES:
        errors.append(
            f"'category' must be one of {KNOWN_CATEGORIES}, got {category_val!r}"
        )

    return len(errors) == 0, errors


def dependency_check(name: str, base_path: str = _PLUGINS_BASE) -> tuple[bool, list[str]]:
    """Check whether all dependencies of a plugin are present in the registry.

    A dependency is considered satisfied if a plugin with that name exists in
    the scanned plugin list (regardless of enabled status).

    Args:
        name:       Plugin name to check.
        base_path:  Root plugins directory.

    Returns:
        (satisfied, missing) — satisfied is True when missing is empty.
        If the plugin itself is not found, returns (False, ["<name> not found"]).
    """
    plugin = get_plugin(name, base_path)
    if plugin is None:
        return False, [f"{name} not found in registry"]

    deps: list[str] = plugin.get("dependencies") or []
    if not deps:
        return True, []

    # Build a set of all known plugin names for O(1) lookup
    all_names = {p["name"].lower() for p in scan_plugins(base_path)}
    missing = [d for d in deps if d.lower() not in all_names]
    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# __main__ smoke test (>= 8 assertions)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    PASS = 0
    FAIL = 0

    def _test(label: str, condition: bool, detail: str = "") -> None:
        global PASS, FAIL
        if condition:
            PASS += 1
            print(f"  PASS  {label}")
        else:
            FAIL += 1
            print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))

    print("=" * 60)
    print("  plugin_registry.py — smoke test")
    print("=" * 60)

    # ── Test 1: scan_plugins returns a list ──────────────────────────
    plugins = scan_plugins(use_cache=False)
    _test(
        "scan_plugins() returns a list",
        isinstance(plugins, list),
        f"got {type(plugins).__name__}",
    )

    # ── Test 2: each record has required keys ────────────────────────
    REQUIRED_KEYS = {"name", "version", "description", "category", "enabled", "dependencies", "source", "path"}
    bad_records = [p for p in plugins if not REQUIRED_KEYS.issubset(p.keys())]
    _test(
        "all plugin records have required keys",
        len(bad_records) == 0,
        f"{len(bad_records)} records missing keys",
    )

    # ── Test 3: all categories are valid ────────────────────────────
    bad_cats = [p for p in plugins if p.get("category") not in KNOWN_CATEGORIES]
    _test(
        "all plugin categories are in KNOWN_CATEGORIES",
        len(bad_cats) == 0,
        f"bad categories: {[p['name'] for p in bad_cats]}",
    )

    # ── Test 4: get_plugin returns a dict for a known plugin ─────────
    if plugins:
        first_name = plugins[0]["name"]
        result = get_plugin(first_name)
        _test(
            f"get_plugin('{first_name}') returns a dict",
            isinstance(result, dict) and result.get("name") == first_name,
            f"got {result}",
        )
    else:
        _test("get_plugin skipped (no plugins found)", True)

    # ── Test 5: get_plugin returns None for unknown name ─────────────
    _test(
        "get_plugin('__nonexistent__') returns None",
        get_plugin("__nonexistent__") is None,
    )

    # ── Test 6: is_enabled returns a bool ────────────────────────────
    enabled_result = is_enabled("__nonexistent__")
    _test(
        "is_enabled('__nonexistent__') returns False",
        enabled_result is False,
        f"got {enabled_result!r}",
    )

    # ── Test 7: get_by_category returns a list ────────────────────────
    dev_plugins = get_by_category("development")
    _test(
        "get_by_category('development') returns a list",
        isinstance(dev_plugins, list),
        f"got {type(dev_plugins).__name__}",
    )
    _test(
        "get_by_category('development') all have category 'development'",
        all(p["category"] == "development" for p in dev_plugins),
        "category mismatch",
    )

    # ── Test 8: validate_plugin on a bad path ──────────────────────
    valid, errors = validate_plugin("/nonexistent/path")
    _test(
        "validate_plugin('/nonexistent/path') returns (False, [error])",
        valid is False and len(errors) > 0,
        f"got valid={valid}, errors={errors}",
    )

    # ── Test 9: validate_plugin on a real marketplace plugin ──────────
    # Find the first plugin directory that has a plugin.json
    real_valid_count = 0
    for p in plugins[:5]:
        v, errs = validate_plugin(p["path"])
        if v:
            real_valid_count += 1
    _test(
        "validate_plugin succeeds for at least one marketplace plugin",
        real_valid_count > 0 or len(plugins) == 0,
        f"0/{min(5, len(plugins))} passed validation",
    )

    # ── Test 10: dependency_check for plugin without deps ─────────────
    no_dep_plugins = [p for p in plugins if not p.get("dependencies")]
    if no_dep_plugins:
        target = no_dep_plugins[0]["name"]
        sat, missing = dependency_check(target)
        _test(
            f"dependency_check('{target}') satisfied=True, missing=[]",
            sat is True and missing == [],
            f"sat={sat}, missing={missing}",
        )
    else:
        _test("dependency_check (no-dep plugin) — no candidates, skipped", True)

    # ── Test 11: dependency_check for unknown plugin ──────────────────
    sat2, missing2 = dependency_check("__ghost__")
    _test(
        "dependency_check('__ghost__') not satisfied",
        sat2 is False and len(missing2) > 0,
        f"sat={sat2}, missing={missing2}",
    )

    # ── Test 12: cache is written and re-read ─────────────────────────
    # Force a fresh scan, then read from cache
    fresh = scan_plugins(use_cache=False)
    cached = scan_plugins(use_cache=True)
    _test(
        "cached scan returns same count as fresh scan",
        len(fresh) == len(cached),
        f"fresh={len(fresh)}, cached={len(cached)}",
    )

    # ── Test 13: _infer_category heuristics ───────────────────────────
    _test(
        "_infer_category('security-guidance', 'warns about security issues') == 'security'",
        _infer_category("security-guidance", "warns about security issues") == "security",
    )
    _test(
        "_infer_category('rust-analyzer-lsp', 'rust LSP') == 'development'",
        _infer_category("rust-analyzer-lsp", "rust LSP") == "development",
    )

    # ── Summary ──────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    print("=" * 60)

    sys.exit(0 if FAIL == 0 else 1)
