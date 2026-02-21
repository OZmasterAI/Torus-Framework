#!/usr/bin/env python3
"""Comprehensive Torus Framework Health Report Generator.

Usage:
    python3 report.py [--brief] [--export]

Generates a comprehensive health report covering:
- Gate operational status (all 17 gates)
- Memory MCP connectivity and knowledge count
- Circuit breaker states and trip counts
- Gate effectiveness metrics (blocks, overrides, prevents)
- Test results summary (passed, failed, failure rate)
- Known issues and status from LIVE_STATE.json
- Ramdisk and audit log health
- Overall framework status recommendations

Options:
  --brief     Summary-only version (no detailed metrics)
  --export    Save report to disk as markdown + JSON
"""

import datetime
import json
import os
import sys
import time

# ── Path constants ─────────────────────────────────────────────────────────────

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
SHARED_DIR = os.path.join(HOOKS_DIR, "shared")
SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
LIVE_STATE_PATH = os.path.join(CLAUDE_DIR, "LIVE_STATE.json")
GATE_EFFECTIVENESS_PATH = os.path.join(HOOKS_DIR, ".gate_effectiveness.json")
STATS_CACHE_PATH = os.path.join(CLAUDE_DIR, "stats-cache.json")

sys.path.insert(0, HOOKS_DIR)

BRIEF_MODE = "--brief" in sys.argv
EXPORT_MODE = "--export" in sys.argv

# ── Status icons ───────────────────────────────────────────────────────────────

ICON_OK = "✓"
ICON_WARN = "⚠"
ICON_ERR = "✗"


# ── Data gathering functions ───────────────────────────────────────────────────

def gather_health_check():
    """Run full_health_check from health_monitor.py."""
    try:
        from shared.health_monitor import full_health_check
        return full_health_check(session_id="main")
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "components": {},
            "overall_score": 0,
        }


def gather_gate_effectiveness():
    """Read .gate_effectiveness.json metrics."""
    if not os.path.exists(GATE_EFFECTIVENESS_PATH):
        return {}
    try:
        with open(GATE_EFFECTIVENESS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def gather_live_state():
    """Read LIVE_STATE.json for project status and known issues."""
    if not os.path.exists(LIVE_STATE_PATH):
        return {}
    try:
        with open(LIVE_STATE_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def gather_stats_cache():
    """Read stats-cache.json for test results."""
    if not os.path.exists(STATS_CACHE_PATH):
        return {}
    try:
        with open(STATS_CACHE_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def gather_shared_modules_integrity():
    """Verify all expected shared modules exist."""
    expected_modules = [
        "health_monitor.py",
        "circuit_breaker.py",
        "error_pattern_analyzer.py",
        "event_bus.py",
        "gate_router.py",
        "state.py",
        "audit_log.py",
        "gate_result.py",
    ]
    status = {}
    for module in expected_modules:
        path = os.path.join(SHARED_DIR, module)
        status[module] = "present" if os.path.exists(path) else "missing"
    return status


def gather_circuit_breaker_states():
    """Get circuit breaker state summary."""
    try:
        from shared.circuit_breaker import get_all_gate_states
        states = get_all_gate_states()
        return states if states else {}
    except Exception as e:
        return {"error": str(e)}


# ── Analysis functions ─────────────────────────────────────────────────────────

def analyze_gate_effectiveness(effectiveness_data):
    """Compute statistics from gate effectiveness metrics."""
    if not effectiveness_data:
        return None

    total_blocks = 0
    total_prevents = 0
    gate_summary = {}

    for gate_name, metrics in effectiveness_data.items():
        blocks = metrics.get("blocks", 0)
        prevents = metrics.get("prevented", 0)
        total_blocks += blocks
        total_prevents += prevents
        gate_summary[gate_name] = {
            "blocks": blocks,
            "prevents": prevents,
            "efficiency": (prevents / blocks) if blocks > 0 else 0,
        }

    return {
        "total_gates": len(gate_summary),
        "total_blocks": total_blocks,
        "total_prevents": total_prevents,
        "prevent_rate": (total_prevents / total_blocks) if total_blocks > 0 else 0,
        "per_gate": gate_summary,
    }


def analyze_test_results(live_state, stats_cache):
    """Extract and analyze test results."""
    test_count = live_state.get("test_count", 0)
    test_failures = live_state.get("test_failures", 0)
    test_passed = test_count - test_failures

    failure_rate = (test_failures / test_count) if test_count > 0 else 0

    return {
        "total": test_count,
        "passed": test_passed,
        "failed": test_failures,
        "failure_rate_pct": failure_rate * 100,
    }


def categorize_known_issues(known_issues):
    """Categorize known issues by type."""
    categories = {
        "platform_limitation": [],
        "performance": [],
        "data_quality": [],
        "integration": [],
        "configuration": [],
        "other": [],
    }

    for issue in known_issues:
        if "platform limitation" in issue.lower() or "tmux" in issue.lower():
            categories["platform_limitation"].append(issue)
        elif "performance" in issue.lower() or "concurrent" in issue.lower():
            categories["performance"].append(issue)
        elif "data" in issue.lower() or "observations" in issue.lower():
            categories["data_quality"].append(issue)
        elif "chromadb" in issue.lower() or "socket" in issue.lower():
            categories["integration"].append(issue)
        elif "hardcoded" in issue.lower() or "config" in issue.lower():
            categories["configuration"].append(issue)
        else:
            categories["other"].append(issue)

    return {k: v for k, v in categories.items() if v}


# ── Report formatting functions ────────────────────────────────────────────────

def format_header(title, level=1):
    """Format a markdown header."""
    hashes = "#" * level
    return f"{hashes} {title}\n"


def format_status_line(icon, label, detail):
    """Format a status line with icon."""
    return f"{icon} **{label}**: {detail}\n"


def format_metric_table(metrics):
    """Format a markdown table for metrics."""
    lines = ["| Metric | Value |", "|--------|-------|"]
    for key, value in metrics.items():
        # Convert key to title case and add formatting
        display_key = key.replace("_", " ").title()
        if isinstance(value, float):
            display_value = f"{value:.2f}"
        else:
            display_value = str(value)
        lines.append(f"| {display_key} | {display_value} |")
    return "\n".join(lines) + "\n"


def build_markdown_report(data):
    """Build the comprehensive markdown report."""
    health_check = data["health_check"]
    effectiveness = data["gate_effectiveness"]
    live_state = data["live_state"]
    test_results = data["test_results"]
    known_issues = data["known_issues"]
    shared_modules = data["shared_modules"]
    circuit_breakers = data["circuit_breakers"]

    report = []

    # ── Title and timestamp ────────────────────────────────────────────
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report.append(format_header("Torus Framework Health Report", 1))
    report.append(f"Generated: {timestamp}\n")

    # ── Executive summary ──────────────────────────────────────────────
    overall_status = health_check.get("status", "unknown").upper()
    overall_score = health_check.get("overall_score", 0)
    status_icon = ICON_OK if overall_score >= 80 else ICON_WARN if overall_score >= 40 else ICON_ERR

    report.append(format_header("Executive Summary", 2))
    report.append(format_status_line(
        status_icon,
        "Overall Status",
        f"{overall_status} ({overall_score}/100 health score)"
    ))

    # Service status from LIVE_STATE
    service_status = live_state.get("service_status", "Unknown")
    report.append(f"\n**Service Status**: {service_status}\n")

    if not BRIEF_MODE:
        # ── Component Status ───────────────────────────────────────────
        report.append(format_header("Component Status", 2))

        components = health_check.get("components", {})
        for comp_name in ["gates", "memory", "state", "ramdisk", "audit"]:
            comp = components.get(comp_name, {})
            comp_status = comp.get("status", "unknown")
            comp_icon = ICON_OK if comp_status == "ok" else ICON_WARN if comp_status == "degraded" else ICON_ERR

            # Extract key details for each component
            if comp_name == "gates":
                summary = comp.get("summary", {})
                detail = f"{summary.get('ok', 0)} operational, {summary.get('error', 0)} errors"
            elif comp_name == "memory":
                detail = f"{'Connected' if comp.get('worker_reachable') else 'Disconnected'}"
                if comp.get("knowledge_count") is not None:
                    detail += f" ({comp.get('knowledge_count')} memories)"
            elif comp_name == "state":
                detail = "Valid JSON" if comp.get("valid_json") else "Missing/Invalid"
            elif comp_name == "ramdisk":
                detail = f"{'Available' if comp.get('ramdisk_available') else 'Using disk fallback'}"
            elif comp_name == "audit":
                detail = f"{'Writable' if comp.get('writable') else 'Not writable'}"
            else:
                detail = comp_status

            report.append(format_status_line(comp_icon, comp_name.title(), detail))

        # Degraded components with suggestions
        degraded = health_check.get("degraded_components", [])
        if degraded:
            report.append("\n**Attention Required**:\n")
            for comp in degraded:
                report.append(f"- {comp.upper()}\n")

        # ── Test Results ───────────────────────────────────────────────
        report.append(format_header("Test Results", 2))
        report.append(format_metric_table({
            "total_tests": test_results["total"],
            "passed": test_results["passed"],
            "failed": test_results["failed"],
            "failure_rate": f"{test_results['failure_rate_pct']:.1f}%",
        }))

        # ── Gate Effectiveness ─────────────────────────────────────────
        if effectiveness:
            report.append(format_header("Gate Effectiveness Metrics", 2))
            analysis = analyze_gate_effectiveness(effectiveness)
            if analysis:
                report.append(format_metric_table({
                    "total_gates": analysis["total_gates"],
                    "total_blocks": analysis["total_blocks"],
                    "prevented_issues": analysis["total_prevents"],
                    "prevention_rate": f"{analysis['prevent_rate']*100:.1f}%",
                }))

                report.append("\n**Top Blocking Gates** (by block count):\n")
                sorted_gates = sorted(
                    analysis["per_gate"].items(),
                    key=lambda x: x[1]["blocks"],
                    reverse=True
                )[:5]
                for gate_name, metrics in sorted_gates:
                    clean_name = gate_name.replace("gate_", "").replace("_", " ").title()
                    report.append(f"- {clean_name}: {metrics['blocks']} blocks, {metrics['prevents']} prevented\n")

        # ── Known Issues ───────────────────────────────────────────────
        if known_issues:
            report.append(format_header("Known Issues", 2))
            categorized = categorize_known_issues(known_issues)
            for category, issues in categorized.items():
                category_display = category.replace("_", " ").title()
                report.append(f"\n**{category_display}** ({len(issues)}):\n")
                for issue in issues:
                    report.append(f"- {issue}\n")

        # ── Shared Modules ─────────────────────────────────────────────
        if shared_modules and any(v != "present" for v in shared_modules.values()):
            report.append(format_header("Shared Module Integrity", 2))
            for module, status in shared_modules.items():
                icon = ICON_OK if status == "present" else ICON_ERR
                report.append(f"{icon} {module}: {status}\n")

    # ── Recommendations ───────────────────────────────────────────────
    report.append(format_header("Recommendations", 2))

    if overall_score >= 80:
        report.append("✓ Framework is healthy. Continue normal operations.\n")
    elif overall_score >= 40:
        report.append(f"⚠ Framework is degraded ({overall_score}/100). Address these issues:\n")
        degraded = health_check.get("degraded_components", [])
        suggestions = health_check.get("fallback_suggestions", {})
        for comp in degraded:
            if comp in suggestions:
                report.append(f"\n**{comp.upper()}**: {suggestions[comp]}\n")
    else:
        report.append("✗ Framework is unhealthy. Critical intervention required.\n")
        report.append("Contact framework maintainer or run /health --repair\n")

    next_steps = live_state.get("next_steps", [])
    if next_steps:
        report.append("\n**Next Steps from LIVE_STATE**:\n")
        for step in next_steps[:3]:  # Show top 3
            report.append(f"- {step}\n")

    return "".join(report)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Gather all data
    data = {
        "health_check": gather_health_check(),
        "gate_effectiveness": gather_gate_effectiveness(),
        "live_state": gather_live_state(),
        "stats_cache": gather_stats_cache(),
        "shared_modules": gather_shared_modules_integrity(),
        "circuit_breakers": gather_circuit_breaker_states(),
        "test_results": analyze_test_results(
            gather_live_state(),
            gather_stats_cache(),
        ),
        "known_issues": gather_live_state().get("known_issues", []),
    }

    # Build markdown report
    markdown_report = build_markdown_report(data)

    # Print to stdout
    print(markdown_report)

    # Optionally export to file
    if EXPORT_MODE:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = os.path.join(
            CLAUDE_DIR,
            f"FRAMEWORK_HEALTH_REPORT_{timestamp}.md"
        )
        try:
            with open(export_file, "w") as f:
                f.write(markdown_report)
            print(f"\n📄 Report exported to: {export_file}\n", file=sys.stderr)

            # Also save JSON
            json_file = export_file.replace(".md", ".json")
            with open(json_file, "w") as f:
                json.dump(data, f, indent=2, default=str)
            print(f"📊 JSON data exported to: {json_file}\n", file=sys.stderr)
        except (OSError, IOError) as e:
            print(f"\n✗ Failed to export report: {e}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
