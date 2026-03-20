#!/usr/bin/env python3
"""Tests for skill_server.py lazy-loading tools: tool_search and tool_describe."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import skill_server as ss

passed = failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))


# score helper
print("\n--- _score_tool_match ---")
test("exact=100", ss._score_tool_match("invoke_skill", "invoke_skill", "d") == 100)
test("substr name=50", ss._score_tool_match("invoke", "invoke_skill", "d") == 50)
test("no match=0", ss._score_tool_match("xyzabc", "invoke_skill", "load a skill") == 0)
test("word in desc=10", ss._score_tool_match("history", "skill_usage", "invocation history") >= 10)

# tool_search
print("\n--- tool_search ---")
r = ss.tool_search("skill")
test("returns dict", isinstance(r, dict))
test("has matches", "matches" in r)
test("total_tools correct", r.get("total_tools", 0) == 6)
test("finds list_skills", any(m["name"] == "list_skills" for m in r["matches"]))
test("no _score in results", all("_score" not in m for m in r["matches"]))
r2 = ss.tool_search("tool_search")
test("exact name ranks first", r2["matches"] and r2["matches"][0]["name"] == "tool_search")
r3 = ss.tool_search("skill", max_results=2)
test("max_results limits", len(r3["matches"]) <= 2)
r4 = ss.tool_search("zzznomatch999")
test("no-match empty", r4["matches"] == [])

# tool_describe
print("\n--- tool_describe ---")
d = ss.tool_describe("invoke_skill")
test("has name", d.get("name") == "invoke_skill")
test("has parameters", isinstance(d.get("parameters"), dict))
test("required=[name]", d.get("required") == ["name"])
d2 = ss.tool_describe("tool_search")
test("self-describe", d2.get("name") == "tool_search")
test("max_results default=5", d2.get("properties", {}).get("max_results", {}).get("default") == 5)
d3 = ss.tool_describe("does_not_exist")
test("nonexist error", "error" in d3)
test("nonexist all_tools", len(d3.get("all_tools", [])) > 0)

# Existing tools unchanged
print("\n--- Existing tools ---")
test("list_skills", isinstance(ss.list_skills(), dict))
test("skill_usage", isinstance(ss.skill_usage(), dict))
test("self_improve", "error" in ss.self_improve("unknown_xyz"))

print(f"\n{chr(61)*50}")
print(f"Skill Server Lazy: {passed} passed, {failed} failed")
import sys; sys.exit(1 if failed else 0)
