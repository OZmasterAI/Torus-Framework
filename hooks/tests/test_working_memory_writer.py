#!/usr/bin/env python3
"""Tests for hooks/shared/working_memory_writer.py

Covers:
- Status section generation
- Operations section with multiple ops
- Expanded section with decisions
- FIFO eviction (>7-8 ops)
- Token cap enforcement (~800)
- Atomic write (file exists after write)
- File format validation (headers present, markdown valid)
"""

import json
import os
import sys
import tempfile
import time

# Add hooks dir to path
HOOKS_DIR = os.path.dirname(os.path.dirname(__file__))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

# ── Test counter ──────────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
RESULTS = []


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(("PASS", name))
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        RESULTS.append(("FAIL", name, detail))
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


# ── Import under test ─────────────────────────────────────────────────────────

from shared.working_memory_writer import (
    WorkingMemoryWriter,
    _token_estimate,
    TOKEN_CAP,
    OPS_SECTION_TOKEN_CAP,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_writer(tmpdir=None):
    """Create a WorkingMemoryWriter with a temp directory."""
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp()
    return WorkingMemoryWriter(tmpdir), tmpdir


def make_op(op_id, op_type="read", purpose="test op", outcome="success", files=None):
    return {
        "id": op_id,
        "type": op_type,
        "purpose": purpose,
        "outcome": outcome,
        "files": files or [f"/tmp/file_{op_id}.py"],
        "tools": ["Read"],
        "start_turn": 1,
        "end_turn": 3,
    }


def make_tracker_state(
    session_id="test-sess",
    current_op_type=None,
    current_op_id=1,
    current_op_purpose="",
    current_op_files=None,
    completed_ops=None,
    decisions=None,
    unresolved_errors=None,
    total_turns=5,
    expand_written=False,
):
    return {
        "_session_id": session_id,
        "_branch": "test-branch",
        "current_op_id": current_op_id,
        "current_op_type": current_op_type,
        "current_op_purpose": current_op_purpose,
        "current_op_files": current_op_files or [],
        "current_op_tools": [],
        "current_op_has_error": False,
        "current_op_has_bash": False,
        "last_turn_timestamp": time.time(),
        "last_tool_phase": None,
        "total_turns": total_turns,
        "total_ops": len(completed_ops or []),
        "expand_written": expand_written,
        "decisions": decisions or [],
        "unresolved_errors": unresolved_errors or [],
        "completed_ops": completed_ops or [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Status section generation
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: Status section ---")

writer, tmpdir = make_writer()

# No active op, no completed ops
state = make_tracker_state()
writer.write_status(state)
path = os.path.join(tmpdir, "working-memory.md")

test("write_status creates file", os.path.exists(path))

with open(path) as f:
    content = f.read()

test("file has markdown header", "# Working Memory" in content)
test("file has Status section", "## Status" in content)
test("Status has Active line", "Active:" in content)
test("Status has Last line", "Last:" in content)
test("no active op shows (none)", "Active: (none)" in content)
test("no last op shows (none)", "Last: (none)" in content)

# Active op present
writer2, tmpdir2 = make_writer()
state2 = make_tracker_state(
    current_op_type="read",
    current_op_id=3,
    current_op_purpose="reading state.py",
    current_op_files=["/hooks/shared/state.py"],
)
writer2.write_status(state2)
with open(os.path.join(tmpdir2, "working-memory.md")) as f:
    content2 = f.read()

test("active op type shown in status", "Op3: read" in content2)
test("active op purpose shown in status", "reading state.py" in content2)
test("active op files shown in status", "state.py" in content2)

# Last completed op
writer3, tmpdir3 = make_writer()
state3 = make_tracker_state(
    completed_ops=[make_op(1, "explore", "Session orient", "success")],
    current_op_type="write",
    current_op_id=2,
    current_op_purpose="implementing feature",
)
writer3.write_status(state3)
with open(os.path.join(tmpdir3, "working-memory.md")) as f:
    content3 = f.read()

test("last completed op shown in status", "Op1: explore" in content3)
test("last completed op outcome shown", "[success]" in content3)

# ─────────────────────────────────────────────────────────────────────────────
# Section 2: Operations section with multiple ops
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: Operations section ---")

writer_ops, tmpdir_ops = make_writer()
ops = [
    make_op(1, "read", "Session orient"),
    make_op(2, "write", "Added state_type column", "success"),
    make_op(3, "verify", "Ran tests", "success"),
]
state_ops = make_tracker_state(completed_ops=ops)
writer_ops.write_operations(state_ops)

with open(os.path.join(tmpdir_ops, "working-memory.md")) as f:
    content_ops = f.read()

test("Operations section header present", "## Operations" in content_ops)
test("Op1 present in operations", "Op1: read" in content_ops)
test("Op2 present in operations", "Op2: write" in content_ops)
test("Op3 present in operations", "Op3: verify" in content_ops)
test("Op outcomes shown", "[success]" in content_ops)

# Each op should mention its purpose
test("Op1 purpose shown", "Session orient" in content_ops)
test("Op2 purpose shown", "Added state_type" in content_ops)

# ─────────────────────────────────────────────────────────────────────────────
# Section 3: FIFO eviction — token-based (~500 tokens cap)
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: FIFO eviction (token-based) ---")

writer_fifo, tmpdir_fifo = make_writer()
many_ops = [
    make_op(i, "read", f"Op {i} purpose text here for testing", "success")
    for i in range(1, 16)
]
state_fifo = make_tracker_state(completed_ops=many_ops)
writer_fifo.write_operations(state_fifo)

with open(os.path.join(tmpdir_fifo, "working-memory.md")) as f:
    content_fifo = f.read()

# Extract just the Operations section to check token budget
ops_start = content_fifo.find("## Operations")
ops_end = content_fifo.find("\n##", ops_start + 1)
if ops_end == -1:
    ops_end = len(content_fifo)
ops_section = content_fifo[ops_start:ops_end]
ops_tokens = _token_estimate(ops_section)

# With 15 ops each ~80 chars (~20 tokens), the ops section should be capped
ops_section_size = content_fifo.count("[Op")
test(
    "FIFO eviction caps ops section under token budget",
    ops_tokens <= OPS_SECTION_TOKEN_CAP,
    f"ops section is {ops_tokens} tokens (cap={OPS_SECTION_TOKEN_CAP}), {ops_section_size} ops",
)
test(
    "FIFO eviction removes some ops (15 input, fewer output)",
    ops_section_size < 15,
    f"found {ops_section_size} ops in file",
)
test(
    "Newest ops retained",
    f"Op{15}:" in content_fifo or f"Op15" in content_fifo,
    f"Op15 not found in content",
)
test(
    "Oldest ops evicted when too many",
    not ("Op1:" in content_fifo and "Op15:" in content_fifo) or ops_section_size <= 10,
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 4: Expanded section with decisions
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: Expanded section ---")

writer_exp, tmpdir_exp = make_writer()
state_exp = make_tracker_state(
    completed_ops=[make_op(1, "read", "Session orient")],
    decisions=[
        "Option 3 confirmed — stay on Claude Code",
        "/clear preferred over /compact",
    ],
    unresolved_errors=[],
    current_op_type="write",
    current_op_id=2,
    current_op_purpose="implementing feature",
)
writer_exp.write_expanded(state_exp)

with open(os.path.join(tmpdir_exp, "working-memory.md")) as f:
    content_exp = f.read()

test("Context section header present after write_expanded", "## Context" in content_exp)
test("Key Decisions subsection present", "### Key Decisions" in content_exp)
test("Decision text captured", "Option 3 confirmed" in content_exp)
test("Unresolved section present", "### Unresolved" in content_exp)
test("expand_written flag set", writer_exp._expand_written is True)

# write_status after write_expanded should include context
writer_exp.write_status(state_exp)
with open(os.path.join(tmpdir_exp, "working-memory.md")) as f:
    content_after_status = f.read()
test(
    "write_status preserves context after expand", "## Context" in content_after_status
)

# clear_expand resets flag
writer_exp.clear_expand()
test("clear_expand resets flag", writer_exp._expand_written is False)

# write_expanded sets expand_written in tracker_state dict (for persistence)
writer_exp2, tmpdir_exp2 = make_writer()
state_exp2 = make_tracker_state(
    completed_ops=[make_op(1, "read", "Session orient")],
    decisions=["Use Option 3"],
    expand_written=False,
)
test("expand_written starts False in state", state_exp2["expand_written"] is False)
writer_exp2.write_expanded(state_exp2)
test(
    "write_expanded sets expand_written=True in tracker_state",
    state_exp2["expand_written"] is True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 5: Token cap enforcement (~800)
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: Token cap enforcement ---")

writer_cap, tmpdir_cap = make_writer()
# Create many ops with long text to exceed cap
big_ops = [
    make_op(
        i,
        "write",
        f"A very long purpose description that uses many words and tokens: iteration {i} with extra text",
        "success",
        files=[f"/very/long/path/to/file_{i}.py", f"/another/long/path/other_{i}.py"],
    )
    for i in range(1, 30)
]
big_decisions = [
    f"Long decision text number {i}: this is a detailed description of the decision taken in this operation with reasoning"
    for i in range(1, 20)
]
state_big = make_tracker_state(
    completed_ops=big_ops,
    decisions=big_decisions,
    current_op_type="write",
    current_op_id=30,
    current_op_purpose="big op",
)
writer_cap.write_expanded(state_big)

token_count = writer_cap.get_token_estimate()
test(
    f"token cap enforced (~{TOKEN_CAP} tokens)",
    token_count <= TOKEN_CAP + 50,  # +50 tolerance for rounding
    f"got {token_count} tokens",
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 6: Atomic write (file exists after write)
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: Atomic write ---")

writer_at, tmpdir_at = make_writer()
state_at = make_tracker_state()

writer_at.write_status(state_at)
file_path_at = os.path.join(tmpdir_at, "working-memory.md")
test("file exists after write_status", os.path.exists(file_path_at))

# No .tmp file should remain
tmp_files = [f for f in os.listdir(tmpdir_at) if ".tmp." in f]
test(
    "no tmp files left after atomic write",
    len(tmp_files) == 0,
    f"found tmp files: {tmp_files}",
)

# get_token_estimate returns int
est = writer_at.get_token_estimate()
test("get_token_estimate returns int", isinstance(est, int))
test("get_token_estimate > 0 for non-empty file", est > 0)

# ─────────────────────────────────────────────────────────────────────────────
# Section 7: File format validation
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: File format validation ---")

writer_fmt, tmpdir_fmt = make_writer()
state_fmt = make_tracker_state(
    completed_ops=[
        make_op(1, "explore", "Session orient"),
        make_op(2, "mutate", "Added column", "success"),
    ],
    current_op_type="verify",
    current_op_id=3,
    current_op_purpose="running tests",
    current_op_files=["/tmp/test.py"],
    decisions=["Use approach A"],
)
writer_fmt.write_expanded(state_fmt)

with open(os.path.join(tmpdir_fmt, "working-memory.md")) as f:
    content_fmt = f.read()

test("markdown h1 header present", content_fmt.startswith("# Working Memory"))
test("session id in header", "Session" in content_fmt)
test("branch in header", "Branch:" in content_fmt)
test("## Status header present", "## Status\n" in content_fmt)
test("## Operations header present", "## Operations\n" in content_fmt)
test("## Context header present after expand", "## Context\n" in content_fmt)
test("op lines start with dash", "- [Op" in content_fmt)
test(
    "outcome in brackets",
    "[success]" in content_fmt
    or "[partial]" in content_fmt
    or "[failure]" in content_fmt,
)

# ─────────────────────────────────────────────────────────────────────────────
# Section 8: Session branch in header
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- WorkingMemoryWriter: Session/branch metadata ---")

writer_meta, tmpdir_meta = make_writer()
state_meta = make_tracker_state(session_id="abc123xyz")
state_meta["_branch"] = "my-feature-branch"
writer_meta.write_status(state_meta)

with open(os.path.join(tmpdir_meta, "working-memory.md")) as f:
    content_meta = f.read()

test(
    "session id shown in file", "abc123xyz" in content_meta or "abc123" in content_meta
)
test("branch shown in file", "my-feature-branch" in content_meta)

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"working_memory_writer tests: {PASS} passed, {FAIL} failed")
if FAIL:
    print("FAILURES:")
    for r in RESULTS:
        if r[0] == "FAIL":
            print(f"  - {r[1]}" + (f": {r[2]}" if len(r) > 2 else ""))
print(f"{'=' * 60}")

if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
