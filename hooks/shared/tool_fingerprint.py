"""Tool fingerprinting for MCP supply chain security.

Tracks SHA256 hashes of tool descriptions and parameters to detect
unexpected changes (rug-pull attacks) between sessions.

Based on Cisco research on MCP tool poisoning / rug-pull attacks where
a trusted tool's description or parameters are silently mutated after
initial trust establishment.
"""
import hashlib
import json
import os
import time

FINGERPRINT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".tool_fingerprints.json")


def fingerprint_tool(tool_name, description="", parameters=None):
    """Generate SHA256 fingerprint of tool metadata.

    Args:
        tool_name: Name of the MCP tool.
        description: Tool description string.
        parameters: Tool parameter schema (dict or None).

    Returns:
        str: Hex-encoded SHA256 digest of the canonical tool metadata.
    """
    canonical = json.dumps(
        {
            "name": tool_name,
            "description": description or "",
            "parameters": parameters or {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_fingerprints():
    """Load fingerprint store from disk. Returns empty dict on missing/corrupt file."""
    if not os.path.exists(FINGERPRINT_FILE):
        return {}
    try:
        with open(FINGERPRINT_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_fingerprints(data):
    """Atomically write fingerprint store to disk.

    Args:
        data: dict mapping tool names to fingerprint records.
    """
    tmp = FINGERPRINT_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, FINGERPRINT_FILE)
    except OSError:
        pass


def register_tool(tool_name, description="", parameters=None):
    """Register or update a tool fingerprint.

    If the tool is new, it is recorded. If it already exists, its hash is
    updated and the change is flagged.

    Args:
        tool_name: Name of the MCP tool.
        description: Tool description string.
        parameters: Tool parameter schema (dict or None).

    Returns:
        tuple: (is_new: bool, changed: bool, old_hash: str|None, new_hash: str)
            - is_new: True if this tool was not previously registered.
            - changed: True if the fingerprint differs from the stored one.
            - old_hash: Previous hash, or None if the tool is new.
            - new_hash: The freshly computed hash.
    """
    new_hash = fingerprint_tool(tool_name, description, parameters)
    store = _load_fingerprints()

    if tool_name not in store:
        store[tool_name] = {
            "hash": new_hash,
            "first_seen": time.time(),
            "last_seen": time.time(),
            "change_count": 0,
        }
        _save_fingerprints(store)
        return (True, False, None, new_hash)

    record = store[tool_name]
    old_hash = record.get("hash")
    changed = old_hash != new_hash

    record["last_seen"] = time.time()
    if changed:
        record["hash"] = new_hash
        record["change_count"] = record.get("change_count", 0) + 1
        record["previous_hash"] = old_hash

    _save_fingerprints(store)
    return (False, changed, old_hash, new_hash)


def check_tool_integrity(tool_name, description="", parameters=None):
    """Check if a tool's fingerprint matches the stored record.

    Does NOT update the store — purely a read + compare operation.

    Args:
        tool_name: Name of the MCP tool.
        description: Tool description string.
        parameters: Tool parameter schema (dict or None).

    Returns:
        tuple: (matches: bool, old_hash: str|None, new_hash: str)
            - If the tool is not registered, returns (True, None, new_hash)
              because there is nothing to compare against (treat as new/trusted).
            - If registered, returns (matches, stored_hash, computed_hash).
    """
    new_hash = fingerprint_tool(tool_name, description, parameters)
    store = _load_fingerprints()

    if tool_name not in store:
        return (True, None, new_hash)

    old_hash = store[tool_name].get("hash")
    matches = old_hash == new_hash
    return (matches, old_hash, new_hash)


def get_all_fingerprints():
    """Return all registered tool fingerprints.

    Returns:
        dict: Mapping of tool_name -> fingerprint record dict.
              Each record contains at minimum: hash, first_seen, last_seen, change_count.
    """
    return _load_fingerprints()


def get_changed_tools():
    """Return list of tools whose fingerprints changed since registration.

    A tool is considered changed if its change_count > 0.

    Returns:
        list[dict]: Each entry has keys: tool_name, current_hash, previous_hash,
                    change_count, last_seen.
    """
    store = _load_fingerprints()
    changed = []
    for tool_name, record in store.items():
        if record.get("change_count", 0) > 0:
            changed.append(
                {
                    "tool_name": tool_name,
                    "current_hash": record.get("hash"),
                    "previous_hash": record.get("previous_hash"),
                    "change_count": record.get("change_count", 0),
                    "last_seen": record.get("last_seen"),
                }
            )
    return changed
