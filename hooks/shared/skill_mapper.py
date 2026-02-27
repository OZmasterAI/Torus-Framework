#!/usr/bin/env python3
"""Skill dependency and health analyzer for the Torus framework.

This module scans all skills in ~/.claude/skills/, parses their
metadata and scripts, and builds a comprehensive dependency graph to identify
missing dependencies, code reuse opportunities, and overall skill health.

Usage (programmatic):
    from shared.skill_mapper import SkillMapper
    mapper = SkillMapper()
    health = mapper.get_skill_health()
    for skill_name, status in health.items():
        print(f"{skill_name}: {status}")
"""

import ast
import glob
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any

# ── Constants ──────────────────────────────────────────────────────────────

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
SKILLS_DIR = os.path.join(CLAUDE_DIR, "skills")
HOOKS_DIR = os.path.join(CLAUDE_DIR, "hooks")
SHARED_DIR = os.path.join(HOOKS_DIR, "shared")

# Standard shared modules that skills commonly use or should use
KNOWN_SHARED_MODULES = {
    "health_monitor": "Health checking and component status",
    "circuit_breaker": "Circuit breaker state management",
    "error_pattern_analyzer": "Error pattern detection and analysis",
    "event_bus": "Event publishing and subscription",
    "gate_router": "Gate routing and orchestration",
    "state": "State file management and persistence",
    "audit_log": "Audit logging and tracking",
    "gate_result": "Gate result data structures",
    "anomaly_detector": "Anomaly detection and pattern recognition",
    "rate_limiter": "Rate limiting and throttling",
    "retry_strategy": "Retry logic and backoff strategies",
    "session_analytics": "Session metrics and analysis",
    "metrics_collector": "Metrics collection and aggregation",
    "config_validator": "Configuration validation",
    "chromadb_socket": "ChromaDB socket communication",
    "capability_registry": "Capability registration and discovery",
    "consensus_validator": "Multi-party consensus validation",
    "error_normalizer": "Error normalization and classification",
    "observation": "Observation data structures and handling",
    "hook_cache": "Hook result caching",
    "plugin_registry": "Plugin registration and management",
    "ramdisk": "Ramdisk management",
    "security_profiles": "Security profile definitions",
    "tool_fingerprint": "Tool fingerprinting",
}


@dataclass
class SkillMetadata:
    """Metadata for a skill."""
    name: str
    path: str
    skill_md_path: str
    script_paths: List[str]
    imports_from_shared: Set[str]
    imports_external: Set[str]
    missing_shared_modules: Set[str]
    functions_defined: Set[str]
    functions_called: Set[str]
    file_count: int


@dataclass
class SkillHealth:
    """Health status for a skill."""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    coverage_pct: float  # % of shared modules used vs potentially useful
    has_metadata: bool
    has_scripts: bool
    script_count: int
    shared_module_count: int
    missing_dependencies: List[str]
    reuse_opportunities: List[str]
    description: str


class SkillMapper:
    """Analyzes skill structure, dependencies, and health."""

    def __init__(self):
        """Initialize the skill mapper."""
        self.skills: Dict[str, SkillMetadata] = {}
        self.dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self.shared_module_usage: Dict[str, List[str]] = defaultdict(list)
        self._scan_skills()

    def _scan_skills(self) -> None:
        """Scan skills directory and build metadata for each skill."""
        if not os.path.isdir(SKILLS_DIR):
            return

        for skill_dir in sorted(glob.glob(os.path.join(SKILLS_DIR, "*"))):
            if not os.path.isdir(skill_dir):
                continue

            skill_name = os.path.basename(skill_dir)
            self._analyze_skill(skill_name, skill_dir)

    def _analyze_skill(self, skill_name: str, skill_dir: str) -> None:
        """Analyze a single skill directory."""
        skill_md_path = os.path.join(skill_dir, "SKILL.md")
        scripts_dir = os.path.join(skill_dir, "scripts")

        # Find all Python scripts
        script_paths = []
        if os.path.isdir(scripts_dir):
            script_paths = sorted(glob.glob(os.path.join(scripts_dir, "*.py")))

        # Parse scripts to extract dependencies
        imports_from_shared = set()
        imports_external = set()
        functions_defined = set()
        functions_called = set()

        for script_path in script_paths:
            self._extract_script_info(
                script_path,
                imports_from_shared,
                imports_external,
                functions_defined,
                functions_called,
            )

        # Identify missing dependencies
        missing_deps = self._identify_missing_dependencies(
            imports_from_shared, functions_called
        )

        metadata = SkillMetadata(
            name=skill_name,
            path=skill_dir,
            skill_md_path=skill_md_path,
            script_paths=script_paths,
            imports_from_shared=imports_from_shared,
            imports_external=imports_external,
            missing_shared_modules=missing_deps,
            functions_defined=functions_defined,
            functions_called=functions_called,
            file_count=len(script_paths),
        )

        self.skills[skill_name] = metadata

        # Update dependency graphs
        for module in imports_from_shared:
            self.dependency_graph[skill_name].add(module)
            self.shared_module_usage[module].append(skill_name)
            self.reverse_dependency_graph[module].add(skill_name)

    def _extract_script_info(
        self,
        script_path: str,
        imports_from_shared: Set[str],
        imports_external: Set[str],
        functions_defined: Set[str],
        functions_called: Set[str],
    ) -> None:
        """Extract imports and function info from a Python script."""
        try:
            with open(script_path, "r") as f:
                source = f.read()
        except (OSError, IOError):
            return

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        # Extract imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "shared" or (
                    node.module and node.module.startswith("shared.")
                ):
                    for alias in node.names:
                        name = alias.name
                        if name != "*":
                            imports_from_shared.add(name)
                elif node.module and not node.module.startswith("."):
                    imports_external.add(node.module.split(".")[0])

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod != "shared":
                        imports_external.add(mod)

            # Extract function definitions
            elif isinstance(node, ast.FunctionDef):
                functions_defined.add(node.name)

        # Extract function calls (simple pattern matching for common patterns)
        for match in re.finditer(
            r"\b([a-z_][a-z0-9_]*)\s*\(", source, re.IGNORECASE
        ):
            functions_called.add(match.group(1))

    def _identify_missing_dependencies(
        self, imports_from_shared: Set[str], functions_called: Set[str]
    ) -> Set[str]:
        """Identify shared modules that are called but not imported."""
        missing = set()

        # Check for direct shared module usage patterns
        for module_name in KNOWN_SHARED_MODULES:
            # Check if module is used in function calls but not imported
            if module_name in functions_called and module_name not in imports_from_shared:
                missing.add(module_name)

        return missing

    def get_skill_health(self) -> Dict[str, SkillHealth]:
        """Compute health status for all skills."""
        health_report = {}

        for skill_name, metadata in self.skills.items():
            shared_used = len(metadata.imports_from_shared)
            missing_deps = len(metadata.missing_shared_modules)

            # Coverage: % of potentially useful shared modules being used
            total_useful = shared_used + missing_deps
            if total_useful > 0:
                coverage = (shared_used / total_useful) * 100
            else:
                coverage = 100 if shared_used == 0 else 0

            # Find reuse opportunities
            reuse_opportunities = self._identify_reuse_opportunities(metadata)

            # Determine status
            if missing_deps > 0:
                status = "unhealthy"
            elif len(reuse_opportunities) >= 3:
                status = "degraded"
            else:
                status = "healthy"

            # Build description
            has_skill_md = os.path.exists(metadata.skill_md_path)
            has_scripts = len(metadata.script_paths) > 0
            description = f"Scripts: {len(metadata.script_paths)}, "
            description += f"Shared modules used: {shared_used}, "
            description += f"Metadata: {'yes' if has_skill_md else 'no'}"

            health = SkillHealth(
                name=skill_name,
                status=status,
                coverage_pct=coverage,
                has_metadata=has_skill_md,
                has_scripts=has_scripts,
                script_count=len(metadata.script_paths),
                shared_module_count=shared_used,
                missing_dependencies=sorted(metadata.missing_shared_modules),
                reuse_opportunities=reuse_opportunities,
                description=description,
            )

            health_report[skill_name] = health

        return health_report

    def _identify_reuse_opportunities(self, metadata: SkillMetadata) -> List[str]:
        """Identify shared modules that could benefit this skill."""
        opportunities = []

        for module_name, description in KNOWN_SHARED_MODULES.items():
            if module_name in metadata.imports_from_shared:
                continue  # Already using this module

            if module_name in metadata.missing_shared_modules:
                continue  # Already identified as missing

            # Check if this module would be useful based on skill functions
            if self._module_would_be_useful(module_name, metadata):
                opportunities.append(
                    f"{module_name}: {description}"
                )

        return opportunities[:5]  # Top 5 opportunities

    def _module_would_be_useful(self, module_name: str, metadata: SkillMetadata) -> bool:
        """Heuristically determine if a shared module would be useful."""
        # Health module useful for skills that do health checks
        if module_name == "health_monitor" and any(
            fn in metadata.functions_called for fn in ["check", "verify", "diagnose"]
        ):
            return True

        # Audit log useful for skills that log or track things
        if module_name == "audit_log" and any(
            fn in metadata.functions_called for fn in ["log", "track", "record"]
        ):
            return True

        # Error pattern analyzer useful for error-related skills
        if module_name == "error_pattern_analyzer" and any(
            fn in metadata.functions_called for fn in ["error", "exception", "fail"]
        ):
            return True

        # State useful for skills that manage state
        if module_name == "state" and any(
            fn in metadata.functions_called for fn in ["state", "save", "load", "persist"]
        ):
            return True

        # Metrics collector useful for skills that collect metrics
        if module_name == "metrics_collector" and any(
            fn in metadata.functions_called for fn in ["metric", "count", "measure"]
        ):
            return True

        # Rate limiter useful for skills that run frequently
        if module_name == "rate_limiter" and any(
            fn in metadata.functions_called for fn in ["limit", "throttle", "rate"]
        ):
            return True

        return False

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """Return skill -> shared modules dependency mapping."""
        return {
            skill: sorted(list(modules))
            for skill, modules in self.dependency_graph.items()
            if modules
        }

    def get_reverse_dependency_graph(self) -> Dict[str, List[str]]:
        """Return shared module -> skills mapping (which skills use each module)."""
        return {
            module: sorted(list(skills))
            for module, skills in self.reverse_dependency_graph.items()
            if skills
        }

    def get_shared_module_usage(self) -> Dict[str, int]:
        """Return usage count for each shared module."""
        return {
            module: len(skills) for module, skills in self.shared_module_usage.items()
        }

    def get_skills_needing_dependencies(self) -> Dict[str, List[str]]:
        """Return skills that have missing dependencies."""
        result = {}
        for skill_name, metadata in self.skills.items():
            if metadata.missing_shared_modules:
                result[skill_name] = sorted(metadata.missing_shared_modules)
        return result

    def get_skills_with_reuse_opportunities(self) -> Dict[str, List[str]]:
        """Return skills that could benefit from more shared module usage."""
        result = {}
        health_report = self.get_skill_health()

        for skill_name, health in health_report.items():
            if health.reuse_opportunities:
                result[skill_name] = health.reuse_opportunities

        return result

    def generate_report(self) -> str:
        """Generate a comprehensive text report of skill analysis."""
        lines = []
        lines.append("=" * 80)
        lines.append("SKILL DEPENDENCY AND HEALTH REPORT")
        lines.append("=" * 80)
        lines.append("")

        health_report = self.get_skill_health()

        # ── Summary section ────────────────────────────────────────────────
        lines.append("SUMMARY")
        lines.append("-" * 80)
        total_skills = len(self.skills)
        healthy = sum(1 for h in health_report.values() if h.status == "healthy")
        degraded = sum(1 for h in health_report.values() if h.status == "degraded")
        unhealthy = sum(1 for h in health_report.values() if h.status == "unhealthy")

        lines.append(f"Total skills: {total_skills}")
        lines.append(f"  - Healthy:   {healthy}")
        lines.append(f"  - Degraded:  {degraded}")
        lines.append(f"  - Unhealthy: {unhealthy}")
        lines.append("")

        # ── Dependency graph section ───────────────────────────────────────
        lines.append("SKILL DEPENDENCIES (skills using shared modules)")
        lines.append("-" * 80)
        dep_graph = self.get_dependency_graph()
        if dep_graph:
            for skill in sorted(dep_graph.keys()):
                modules = dep_graph[skill]
                lines.append(f"{skill}: {', '.join(modules)}")
        else:
            lines.append("(no skills using shared modules)")
        lines.append("")

        # ── Shared module usage section ────────────────────────────────────
        lines.append("SHARED MODULE USAGE (most used first)")
        lines.append("-" * 80)
        usage = self.get_shared_module_usage()
        if usage:
            for module, count in sorted(usage.items(), key=lambda x: x[1], reverse=True):
                skills = self.shared_module_usage[module]
                lines.append(f"{module} ({count} skills): {', '.join(sorted(skills))}")
        else:
            lines.append("(no shared modules being used)")
        lines.append("")

        # ── Missing dependencies section ───────────────────────────────────
        missing_by_skill = self.get_skills_needing_dependencies()
        if missing_by_skill:
            lines.append("SKILLS WITH MISSING DEPENDENCIES")
            lines.append("-" * 80)
            for skill in sorted(missing_by_skill.keys()):
                modules = missing_by_skill[skill]
                lines.append(f"{skill}: {', '.join(modules)}")
            lines.append("")

        # ── Reuse opportunities section ────────────────────────────────────
        reuse_opps = self.get_skills_with_reuse_opportunities()
        if reuse_opps:
            lines.append("SKILLS WITH SHARED MODULE REUSE OPPORTUNITIES")
            lines.append("-" * 80)
            for skill in sorted(reuse_opps.keys()):
                lines.append(f"\n{skill}:")
                for opp in reuse_opps[skill][:3]:  # Top 3
                    lines.append(f"  - {opp}")
            lines.append("")

        # ── Detailed health section ────────────────────────────────────────
        lines.append("DETAILED SKILL HEALTH")
        lines.append("-" * 80)
        for skill in sorted(health_report.keys()):
            health = health_report[skill]
            status_sym = (
                "HEALTHY"
                if health.status == "healthy"
                else "DEGRADED" if health.status == "degraded" else "UNHEALTHY"
            )
            lines.append(
                f"{skill}: {status_sym} (coverage: {health.coverage_pct:.0f}%, "
                f"scripts: {health.script_count}, modules: {health.shared_module_count})"
            )
            if health.missing_dependencies:
                lines.append(f"  Missing: {', '.join(health.missing_dependencies)}")
            if health.reuse_opportunities:
                lines.append(f"  Opportunities:")
                for opp in health.reuse_opportunities[:2]:
                    lines.append(f"    - {opp}")

        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)


def main():
    """CLI entry point."""
    mapper = SkillMapper()
    print(mapper.generate_report())


if __name__ == "__main__":
    main()
