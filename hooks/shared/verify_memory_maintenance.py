"""Verification script for shared/memory_maintenance.py.

Run with: python3 ~/.claude/hooks/shared/verify_memory_maintenance.py
Uses sentinel pattern for ts parameter to correctly test empty-string timestamp.
"""
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))

from shared.memory_maintenance import (
    _split_tags, _age_days, _has_session_reference,
    _has_superseded_language, _tag_distribution, _count_stats,
    _similarity_groups, _stale_memory_scan, _build_recommendations,
    cleanup_candidates, analyze_memory_health,
    STALE_THRESHOLD_DAYS, ANCIENT_THRESHOLD_DAYS,
)

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}")
        FAIL += 1


now = datetime.now(timezone.utc)
fresh_ts = (now - timedelta(days=10)).isoformat()
recent_ts = (now - timedelta(days=60)).isoformat()
aging_ts = (now - timedelta(days=120)).isoformat()
stale_ts = (now - timedelta(days=200)).isoformat()

_SENTINEL = object()


def mk(id_, doc="doc", tags="type:fix", ts=_SENTINEL, preview=""):
    """Build a minimal entry dict. ts=_SENTINEL -> fresh_ts default; ts="" -> unknown age."""
    return {
        "id": id_,
        "document": doc,
        "tags": tags,
        "timestamp": fresh_ts if ts is _SENTINEL else ts,
        "preview": preview,
        "session_time": 0,
        "possible_dupe": "",
    }


# ── _split_tags ────────────────────────────────────────────────────────────────
check("split_tags empty", _split_tags("") == [])
check("split_tags single", _split_tags("type:fix") == ["type:fix"])
check("split_tags multi", _split_tags("type:fix,area:infra, priority:high") == ["type:fix", "area:infra", "priority:high"])
check("split_tags whitespace-only", _split_tags("  ,  ") == [])

# ── _age_days ──────────────────────────────────────────────────────────────────
check("age_days fresh ~10d", 9.5 <= _age_days(fresh_ts, now) <= 10.5)
check("age_days stale ~200d", 199 <= _age_days(stale_ts, now) <= 201)
check("age_days bad ts", _age_days("not-a-date", now) is None)
check("age_days empty", _age_days("", now) is None)
check("age_days Z suffix", _age_days("2026-01-01T00:00:00Z", now) is not None)

# ── _has_session_reference ─────────────────────────────────────────────────────
check("session_ref Session 42", _has_session_reference("Fixed in Session 42"))
check("session_ref session #7", _has_session_reference("see session #7 for context"))
check("session_ref no match", not _has_session_reference("this is a plain memory"))
check("session_ref sprint-2", _has_session_reference("sprint-2 work"))

# ── _has_superseded_language ───────────────────────────────────────────────────
check("superseded 'was fixed'", _has_superseded_language("This bug was fixed upstream"))
check("superseded 'replaced by'", _has_superseded_language("This approach was replaced by the new one"))
check("superseded 'obsolete'", _has_superseded_language("The old system is now obsolete"))
check("superseded no match", not _has_superseded_language("The system works correctly"))
check("superseded 'no longer needed'", _has_superseded_language("No longer needed workaround"))

# ── _count_stats ───────────────────────────────────────────────────────────────
entries_age = [
    mk("a", ts=fresh_ts),
    mk("b", ts=recent_ts),
    mk("c", ts=aging_ts, tags="area:infra"),
    mk("d", ts=stale_ts, tags="area:infra"),
    mk("e", ts=""),  # empty string -> unknown age (not same as sentinel)
]
cs = _count_stats(entries_age, now)
check("count_stats total=5", cs["total"] == 5)
check("count_stats fresh=1", cs["age_buckets"]["fresh_0_30d"] == 1)
check("count_stats recent=1", cs["age_buckets"]["recent_31_90d"] == 1)
check("count_stats aging=1", cs["age_buckets"]["aging_91_180d"] == 1)
check("count_stats stale=1", cs["age_buckets"]["stale_181d_plus"] == 1)
check("count_stats unknown=1", cs["age_buckets"]["unknown_age"] == 1)
check("count_stats median not None", cs["median_age_days"] is not None)
check("count_stats oldest >= 200", cs["oldest_age_days"] is not None and cs["oldest_age_days"] >= 199)
check("count_stats newest <= 11", cs["newest_age_days"] is not None and cs["newest_age_days"] <= 11)

# ── _tag_distribution ──────────────────────────────────────────────────────────
td = _tag_distribution(entries_age)
check("tag_dist total_unique>=2", td["total_unique_tags"] >= 2)
check("tag_dist untagged=0", td["untagged_count"] == 0)
check("tag_dist possible_dupe=0", td["possible_dupe_count"] == 0)
check("tag_dist type:fix count=3", td["category_breakdown"]["type:fix"]["count"] == 3)
check("tag_dist area:infra count=2", td["category_breakdown"]["area:infra"]["count"] == 2)
check("tag_dist underrepresented is list", isinstance(td["underrepresented_categories"], list))
check("tag_dist top_tags is list", isinstance(td["top_tags"], list))
check("tag_dist avg_tags positive", td["avg_tags_per_memory"] > 0)

td2 = _tag_distribution(entries_age + [mk("z", tags="")])
check("tag_dist untagged=1", td2["untagged_count"] == 1)

td3 = _tag_distribution(entries_age + [mk("f", tags="possible-dupe:abc123,type:fix")])
check("tag_dist possible_dupe=1", td3["possible_dupe_count"] == 1)

# ── _similarity_groups ─────────────────────────────────────────────────────────
sg = _similarity_groups([mk(f"c{i}", tags="TRv1,type:fix") for i in range(5)])
check("sim_groups TRv1 cluster found", sg["cluster_count"] >= 1)
check("sim_groups TRv1 size=5", sg["clusters"][0]["size"] == 5)
check("sim_groups singleton=0", sg["singleton_count"] == 0)

sg2 = _similarity_groups([mk(f"s{i}", tags=f"unique-{i}") for i in range(3)])
check("sim_groups singletons=3", sg2["singleton_count"] == 3)
check("sim_groups cluster_count=0", sg2["cluster_count"] == 0)

sg3 = _similarity_groups([mk(f"n{i}", tags="type:fix,priority:high") for i in range(5)])
check("sim_groups noise tags excluded", sg3["cluster_count"] == 0)

# ── _stale_memory_scan ─────────────────────────────────────────────────────────
stale_entries = [
    mk("old_session", doc="Session 42 fixed this", ts=stale_ts),
    mk("superseded", doc="This was replaced by the new system"),
    mk("duped", tags="type:fix,possible-dupe:xyz999"),
    mk("clean", doc="This is a clean, current memory", tags="type:feature"),
]
ss = _stale_memory_scan(stale_entries, now)
check("stale_scan count=3", ss["stale_count"] == 3)
stale_ids = {e["id"] for e in ss["stale_entries"]}
check("stale_scan old_session flagged", "old_session" in stale_ids)
check("stale_scan superseded flagged", "superseded" in stale_ids)
check("stale_scan duped flagged", "duped" in stale_ids)
check("stale_scan clean not flagged", "clean" not in stale_ids)
for e in ss["stale_entries"]:
    check(f"entry {e['id']} has signals", len(e["signals"]) > 0)

# ── _build_recommendations ────────────────────────────────────────────────────
cs_big = {"total": 1100, "age_buckets": {"stale_181d_plus": 60}, "quarantine_count": 250}
td_t = {"untagged_count": 5, "possible_dupe_count": 25, "underrepresented_categories": ["area:docs"]}
recs = _build_recommendations(cs_big, td_t, {"stale_count": 10}, {"largest_cluster_size": 5, "clusters": []})
check("recs is list", isinstance(recs, list))
check("recs not empty", len(recs) > 0)
check("recs mentions volume", any("1100" in r for r in recs))
check("recs mentions quarantine", any("quarantine" in r.lower() for r in recs))
check("recs mentions underrepresented", any("underrepresented" in r.lower() for r in recs))

cs_ok = {"total": 50, "age_buckets": {"stale_181d_plus": 0}, "quarantine_count": 5}
td_ok = {"untagged_count": 0, "possible_dupe_count": 0, "underrepresented_categories": []}
recs_ok = _build_recommendations(cs_ok, td_ok, {"stale_count": 0}, {"largest_cluster_size": 0, "clusters": []})
check("recs healthy message", any("healthy" in r.lower() for r in recs_ok))

recs_lg = _build_recommendations(
    {"total": 100, "age_buckets": {"stale_181d_plus": 0}, "quarantine_count": 0},
    {"untagged_count": 0, "possible_dupe_count": 0, "underrepresented_categories": []},
    {"stale_count": 0},
    {"largest_cluster_size": 60, "clusters": [{"label": "TRv1", "size": 60}]},
)
check("recs large cluster warning", any("cluster" in r.lower() for r in recs_lg))

# ── cleanup_candidates (offline) ─────────────────────────────────────────────
cands = cleanup_candidates()
check("cleanup_candidates is list", isinstance(cands, list))
for c in cands[:3]:
    check(f"candidate tier valid", c.get("tier") in ("strong", "moderate", "soft"))

# ── analyze_memory_health (offline) ──────────────────────────────────────────
report = analyze_memory_health()
check("analyze is dict", isinstance(report, dict))
check("analyze has status", "status" in report)
check("analyze has summary", "summary" in report)
check("analyze has recommendations", "recommendations" in report)
check("analyze has timestamp", "timestamp" in report)
check("analyze has duration_ms", "duration_ms" in report)
check("analyze status valid", report["status"] in ("ok", "degraded", "error"))
check("analyze summary is str", isinstance(report.get("summary"), str))
check("analyze recs is list", isinstance(report.get("recommendations"), list))
check("analyze duration >= 0", report.get("duration_ms", -1) >= 0)
print(f"  INFO  status={report['status']}  summary={report['summary'][:70]}")

print()
print(f"Results: {PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
