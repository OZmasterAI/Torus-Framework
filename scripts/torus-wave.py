#!/usr/bin/env python3
"""torus-wave.py — Wave-based parallel task orchestrator for Torus Framework.

Reads eligible tasks from task_manager.py wave command, groups them into waves
with file-overlap guards, spawns parallel claude -p processes, serializes
validation, and loops until all tasks are done or max iterations reached.

Usage: python3 torus-wave.py <prp-name> [--max-iterations N] [--model sonnet|opus] [--timeout SECONDS]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────
PRP_DIR = os.path.expanduser("~/.claude/PRPs")
TASK_MANAGER = os.path.join(PRP_DIR, "task_manager.py")
PROMPT_TEMPLATE = os.path.expanduser("~/.claude/scripts/torus-prompt.md")
MEMORY_PREFETCH = os.path.expanduser("~/.claude/scripts/memory-prefetch.py")


def log(activity_log, message):
    """Write message to stdout and append to activity log."""
    print(message)
    with open(activity_log, "a") as f:
        f.write(message + "\n")


def get_eligible_tasks(prp_name):
    """Call task_manager.py wave and return list of eligible tasks (or empty if done)."""
    result = subprocess.run(
        [sys.executable, TASK_MANAGER, "wave", prp_name],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        # Exit 1 means done (no eligible tasks)
        return None  # None = done
    try:
        tasks = json.loads(result.stdout)
        if isinstance(tasks, dict) and tasks.get("done"):
            return None
        return tasks
    except json.JSONDecodeError:
        return None


def build_wave(eligible_tasks):
    """Apply file-overlap guard: if two tasks share files, keep one and defer the other.

    Returns (wave_tasks, deferred_tasks). Wave tasks share no files.
    Priority ordering: failed tasks first, then pending (matching cmd_wave order).
    """
    wave = []
    deferred = []
    claimed_files = set()

    for task in eligible_tasks:
        task_files = set(task.get("files", []))
        if task_files & claimed_files:
            # Overlap — defer this task to the next wave
            deferred.append(task)
        else:
            wave.append(task)
            claimed_files |= task_files

    return wave, deferred


def _prefetch_memories(task_name, files):
    """Pre-fetch relevant memories via FTS5 index (read-only, fail-open)."""
    if not os.path.exists(MEMORY_PREFETCH):
        return ""
    try:
        cmd = [sys.executable, MEMORY_PREFETCH, task_name] + files[:3]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return ""


def build_prompt(task, prp_name):
    """Build the claude prompt for a task, with pre-fetched memory context."""
    task_id = task["id"]
    task_name = task["name"]
    files = task.get("files", [])
    file_list = "\n".join(files)
    validate_cmd = task.get("validate", "echo no validation")

    # Pre-fetch relevant memories
    memory_context = _prefetch_memories(task_name, files)

    if os.path.exists(PROMPT_TEMPLATE):
        with open(PROMPT_TEMPLATE) as f:
            template = f.read()
        for key, value in [
            ("task_id", str(task_id)),
            ("prp_name", prp_name),
            ("task_name", task_name),
            ("file_list", file_list),
            ("validate_command", validate_cmd),
        ]:
            template = template.replace("{" + key + "}", value)
        prompt = template
    else:
        prompt = f"""You are executing task {task_id} of PRP "{prp_name}".

## Task
{task_name}

## Files to modify
{file_list}

## Validation
Run this command to verify: `{validate_cmd}`

## Rules
1. Query memory first: search_knowledge("{task_name}")
2. Read all files before editing
3. Implement ONLY this task — do not touch other tasks
4. Run the validation command and show output
5. If validation passes, save to memory: remember_this("Completed task {task_id}: {task_name}", "torus-loop iteration", "type:fix,area:framework")
6. If validation fails, describe what went wrong clearly
7. If you discover something other agents should know, broadcast it:
   ```python
   import sys; sys.path.insert(0, '~/.claude/hooks')
   from shared.agent_channel import post_message
   post_message('task-{task_id}', 'discovery', 'what you found')
   ```
"""

    # Append pre-fetched memories if found
    if memory_context:
        prompt += "\n" + memory_context + "\n"

    # Inject recent agent messages (fail-open)
    try:
        _hooks = os.path.expanduser("~/.claude/hooks")
        if _hooks not in sys.path:
            sys.path.insert(0, _hooks)
        from shared.agent_channel import read_messages as _read_msgs
        msgs = _read_msgs(since_ts=time.time() - 3600, limit=5)
        if msgs:
            prompt += "\n## Recent Agent Messages\n"
            for m in msgs:
                prompt += f"- [{m['from_agent']}] ({m['msg_type']}): {m['content']}\n"
            prompt += "\n"
    except Exception:
        pass

    # Inject locked decisions from CONTEXT.md (fail-open)
    for context_path in [
        os.path.join(PRP_DIR, prp_name, "CONTEXT.md"),
        os.path.join(PRP_DIR, f"{prp_name}.context.md"),
    ]:
        if os.path.exists(context_path):
            with open(context_path) as f:
                prompt += "\n" + f.read() + "\n"
            break

    return prompt


def mark_in_progress(prp_name, task_id):
    """Mark a task as in_progress (serialized call)."""
    subprocess.run(
        [sys.executable, TASK_MANAGER, "update", prp_name, str(task_id), "in_progress"],
        capture_output=True, text=True
    )


def validate_task(prp_name, task_id):
    """Run validation for a task. Returns True if passed."""
    result = subprocess.run(
        [sys.executable, TASK_MANAGER, "validate", prp_name, str(task_id)],
        capture_output=True, text=True
    )
    return result.returncode == 0


def git_commit_task(task_id, task_name):
    """Git commit a passed task if inside a git repo."""
    try:
        in_repo = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, cwd=os.path.expanduser("~/.claude")
        )
        if in_repo.returncode == 0:
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, cwd=os.path.expanduser("~/.claude")
            )
            subprocess.run(
                ["git", "commit", "-m", f"torus-wave: task {task_id} - {task_name}", "--no-verify"],
                capture_output=True, cwd=os.path.expanduser("~/.claude")
            )
    except Exception:
        pass  # Git commit failure is non-fatal


def spawn_claude(prompt, model, task_timeout):
    """Spawn a claude -p process non-blocking. Returns Popen object."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    cmd = [
        "env", "-u", "CLAUDECODE",
        "timeout", str(task_timeout),
        "claude", "-p", prompt,
        "--dangerously-skip-permissions",
        "--model", model,
    ]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


MAX_RETRIES = 2  # Max auto-restarts per task
CIRCUIT_BREAKER_THRESHOLD = 3  # Consecutive wave failures before stopping


def run_wave(prp_name, wave_tasks, model, task_timeout, activity_log, wave_num):
    """Spawn all wave tasks in parallel, monitor with polling, auto-restart on crash.

    Returns dict mapping task_id -> {"status": "PASSED"|"FAILED", "duration": int, "retries": int}.
    """
    # Serialize: mark all tasks in_progress before spawning
    for task in wave_tasks:
        mark_in_progress(prp_name, task["id"])

    # Track per-task state
    active = {}  # task_id -> {proc, start, task, retries, prompt}
    for task in wave_tasks:
        prompt = build_prompt(task, prp_name)
        start_time = time.time()
        proc = spawn_claude(prompt, model, task_timeout)
        active[task["id"]] = {
            "proc": proc, "start": start_time, "task": task,
            "retries": 0, "prompt": prompt,
        }
        log(activity_log, f"  Spawned task {task['id']}: {task['name']} (pid={proc.pid})")

    # Poll loop: check every 5s, auto-restart crashed processes
    outputs = {}
    while active:
        time.sleep(5)
        done_ids = []
        for task_id, info in active.items():
            proc = info["proc"]
            rc = proc.poll()
            if rc is None:
                # Still running — safety-net timeout (timeout wrapper + 30s grace)
                if time.time() - info["start"] > task_timeout + 30:
                    proc.kill()
                    proc.wait()
                    log(activity_log, f"  Task {task_id}: killed (exceeded timeout + 30s grace)")
                    rc = -9
                else:
                    continue

            # Process finished (or was killed)
            duration = int(time.time() - info["start"])
            stdout = ""
            try:
                stdout = proc.stdout.read() or ""
            except Exception:
                pass

            if rc != 0 and info["retries"] < MAX_RETRIES:
                # Auto-restart: non-zero exit, retries remaining
                info["retries"] += 1
                log(activity_log, f"  Task {task_id}: crashed (exit={rc}), auto-restart {info['retries']}/{MAX_RETRIES}")
                new_proc = spawn_claude(info["prompt"], model, task_timeout)
                info["proc"] = new_proc
                info["start"] = time.time()
                log(activity_log, f"  Task {task_id}: restarted (new pid={new_proc.pid})")
            else:
                outputs[task_id] = {
                    "stdout": stdout, "duration": duration,
                    "task": info["task"], "claude_exit": rc,
                    "retries": info["retries"],
                }
                done_ids.append(task_id)

        for tid in done_ids:
            del active[tid]

    # Serialize validation (one at a time to avoid tasks.json write races)
    results = {}
    for task_id, info in outputs.items():
        task = info["task"]
        passed = validate_task(prp_name, task_id)
        status = "PASSED" if passed else "FAILED"
        retries = info["retries"]
        results[task_id] = {"status": status, "duration": info["duration"], "retries": retries}

        retry_note = f" (after {retries} restart{'s' if retries != 1 else ''})" if retries > 0 else ""
        log(activity_log, f"  Task {task_id} ({task['name']}): {status} in {info['duration']}s{retry_note}")

        # Post result to agent channel (fail-open)
        try:
            _hooks = os.path.expanduser("~/.claude/hooks")
            if _hooks not in sys.path:
                sys.path.insert(0, _hooks)
            from shared.agent_channel import post_message as _post_msg
            _post_msg(f"wave-{wave_num}", "result", f"Task {task_id} ({task['name']}): {status}{retry_note}")
        except Exception:
            pass

        # Log on_fail routing if applicable
        if not passed and task.get("on_fail") is not None:
            log(activity_log, f"  on_fail routing → task {task['on_fail']} activated")

        if passed:
            git_commit_task(task_id, task["name"])

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Wave-based parallel task orchestrator for Torus Framework."
    )
    parser.add_argument("prp_name", nargs="?", help="PRP name to execute")
    parser.add_argument("--max-iterations", type=int, default=50,
                        help="Maximum number of wave iterations (default: 50)")
    parser.add_argument("--model", default="sonnet",
                        choices=["sonnet", "opus"],
                        help="Claude model to use (default: sonnet)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout per task in seconds (default: 600)")
    args = parser.parse_args()

    if not args.prp_name:
        parser.print_help()
        sys.exit(1)

    prp_name = args.prp_name
    max_iterations = args.max_iterations
    model = args.model
    task_timeout = args.timeout

    # Validate prerequisites
    tasks_file = os.path.join(PRP_DIR, f"{prp_name}.tasks.json")
    if not os.path.exists(tasks_file):
        print(f"Error: Tasks file not found: {tasks_file}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(TASK_MANAGER):
        print(f"Error: task_manager.py not found at {TASK_MANAGER}", file=sys.stderr)
        sys.exit(1)

    # Validate claude CLI is available
    if subprocess.run(["which", "claude"], capture_output=True).returncode != 0:
        print("Error: 'claude' CLI not found in PATH", file=sys.stderr)
        sys.exit(1)

    activity_log = os.path.join(PRP_DIR, f"{prp_name}.activity.md")
    stop_sentinel = os.path.join(PRP_DIR, f"{prp_name}.stop")

    # Remove stale stop sentinel
    if os.path.exists(stop_sentinel):
        os.remove(stop_sentinel)

    # Initialize activity log
    with open(activity_log, "w") as f:
        f.write(f"# Torus Wave: {prp_name}\n\n")
        f.write(f"**Started**: {datetime.now().isoformat()}\n")
        f.write(f"**Model**: {model}\n")
        f.write(f"**Max iterations**: {max_iterations}\n")
        f.write(f"**Mode**: parallel (wave-based)\n\n")
        f.write("---\n\n")

    # Clean up old agent messages at startup (fail-open)
    try:
        _hooks = os.path.expanduser("~/.claude/hooks")
        if _hooks not in sys.path:
            sys.path.insert(0, _hooks)
        from shared.agent_channel import cleanup as _channel_cleanup
        _channel_cleanup()
    except Exception:
        pass

    print(f"Starting torus-wave for PRP: {prp_name}")
    print(f"Model: {model} | Max iterations: {max_iterations} | Timeout: {task_timeout}s")
    print()

    iteration = 0
    consecutive_failures = 0  # Circuit breaker counter
    total_passed = 0
    total_failed = 0
    wave_start_time = time.time()

    while iteration < max_iterations:
        iteration += 1

        # Check stop sentinel
        if os.path.exists(stop_sentinel):
            log(activity_log, f"## Wave {iteration}: STOPPED BY SENTINEL")
            os.remove(stop_sentinel)
            print("Stop sentinel detected. Exiting gracefully.")
            sys.exit(0)

        # Get eligible tasks
        eligible = get_eligible_tasks(prp_name)
        if eligible is None:
            elapsed = int(time.time() - wave_start_time)
            log(activity_log, "\n## COMPLETE\n")
            with open(activity_log, "a") as f:
                f.write(f"**Finished**: {datetime.now().isoformat()}\n")
                f.write(f"**Total**: {total_passed} passed, {total_failed} failed in {elapsed}s across {iteration - 1} waves\n")
            print("All tasks complete!")
            sys.exit(0)

        # Apply file-overlap guard to build this wave
        wave_tasks, deferred = build_wave(eligible)

        if not wave_tasks:
            # All eligible tasks were deferred (shouldn't normally happen)
            log(activity_log, f"## Wave {iteration}: No tasks could be launched (all deferred due to file overlap)")
            break

        deferred_ids = [t["id"] for t in deferred]
        log(activity_log, f"\n### Wave {iteration} — {len(wave_tasks)} task(s) in parallel")
        if deferred_ids:
            log(activity_log, f"  Deferred (file overlap): task IDs {deferred_ids}")

        print(f"[Wave {iteration}/{max_iterations}] Launching {len(wave_tasks)} task(s): "
              f"{[t['id'] for t in wave_tasks]}")
        if deferred_ids:
            print(f"  Deferred to next wave (file overlap): {deferred_ids}")

        # Run the wave
        results = run_wave(prp_name, wave_tasks, model, task_timeout, activity_log, iteration)

        # Summary with metrics
        passed = sum(1 for r in results.values() if r["status"] == "PASSED")
        failed = sum(1 for r in results.values() if r["status"] == "FAILED")
        wave_duration = sum(r["duration"] for r in results.values())
        total_passed += passed
        total_failed += failed

        log(activity_log, f"  Wave {iteration} complete: {passed} passed, {failed} failed ({wave_duration}s)\n")
        print(f"  Wave {iteration} complete: {passed} passed, {failed} failed")
        print()

        # Circuit breaker: stop after N consecutive all-fail waves
        if passed == 0 and failed > 0:
            consecutive_failures += 1
            if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                elapsed = int(time.time() - wave_start_time)
                log(activity_log, f"\n## CIRCUIT BREAKER: {consecutive_failures} consecutive failed waves. Stopping.")
                with open(activity_log, "a") as f:
                    f.write(f"**Stopped**: {datetime.now().isoformat()} (circuit breaker)\n")
                    f.write(f"**Total**: {total_passed} passed, {total_failed} failed in {elapsed}s\n")
                print(f"Circuit breaker triggered: {consecutive_failures} consecutive failed waves.")
                sys.exit(1)
        else:
            consecutive_failures = 0

    # Max iterations reached
    elapsed = int(time.time() - wave_start_time)
    log(activity_log, "\n## MAX ITERATIONS REACHED")
    with open(activity_log, "a") as f:
        f.write(f"**Finished**: {datetime.now().isoformat()}\n")
        f.write(f"**Total**: {total_passed} passed, {total_failed} failed in {elapsed}s across {iteration} waves\n")
    print(f"Max iterations ({max_iterations}) reached.")
    sys.exit(1)


if __name__ == "__main__":
    main()
