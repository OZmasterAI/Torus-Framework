#!/usr/bin/env python3
"""Tests for modules with zero coverage:
- action_patterns.py
- memory_quality.py
- model_profiles.py
- search_helpers.py
- tool_profiles.py
- dag_memory.py (bridge functions)
- dag_memory_layer._infer_tags helper
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# action_patterns.py
# ============================================================


class TestActionPatterns:
    def setup_method(self):
        from shared.action_patterns import (
            extract_pattern,
            format_pattern,
            is_error_query,
        )

        self.is_error_query = is_error_query
        self.extract_pattern = extract_pattern
        self.format_pattern = format_pattern

    def test_is_error_query_true_error(self):
        assert self.is_error_query("ImportError: no module named foo") is True

    def test_is_error_query_true_fail(self):
        assert self.is_error_query("test failed with exception") is True

    def test_is_error_query_true_blocked(self):
        assert self.is_error_query("blocked by gate 01") is True

    def test_is_error_query_false_normal(self):
        assert self.is_error_query("how to configure rate limiter") is False

    def test_is_error_query_true_traceback(self):
        assert self.is_error_query("Traceback most recent call") is True

    def test_is_error_query_true_timeout(self):
        assert self.is_error_query("connection timeout") is True

    def test_extract_pattern_basic(self):
        meta = {"confidence": "0.8", "strategy_id": "install_pkg", "outcome": "success"}
        result = self.extract_pattern("ImportError: no module named foo", meta)
        assert result["trigger"] == "ImportError: no module named foo"
        assert result["action"] == "install_pkg"
        assert result["outcome"] == "success"
        assert 0 <= result["confidence"] <= 1.0

    def test_extract_pattern_no_confidence(self):
        meta = {"strategy_id": "retry", "outcome": "failed"}
        result = self.extract_pattern("Network error", meta)
        assert result["confidence"] == 0.0
        assert result["action"] == "retry"

    def test_extract_pattern_temporal_decay(self):
        old_ts = "2020-01-01T00:00:00"
        recent_ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta_old = {"confidence": "0.9", "timestamp": old_ts, "outcome": "success"}
        meta_new = {"confidence": "0.9", "timestamp": recent_ts, "outcome": "success"}
        old_result = self.extract_pattern("error", meta_old)
        new_result = self.extract_pattern("error", meta_new)
        assert old_result["confidence"] < new_result["confidence"]

    def test_extract_pattern_attempts(self):
        meta = {"attempts": "3", "outcome": "success"}
        result = self.extract_pattern("error msg", meta)
        assert result["attempts"] == 3

    def test_extract_pattern_chain_id(self):
        meta = {"chain_id": "chain_abc123"}
        result = self.extract_pattern("error", meta)
        assert result["chain_id"] == "chain_abc123"

    def test_extract_pattern_unknown_action(self):
        result = self.extract_pattern("error", {})
        assert result["action"] == "unknown"

    def test_format_pattern_success(self):
        pattern = {
            "trigger": "ImportError: no module",
            "action": "pip install",
            "outcome": "success",
            "confidence": 0.85,
            "chain_id": "chain_xyz",
            "attempts": 1,
        }
        formatted = self.format_pattern(pattern)
        assert isinstance(formatted, str)
        assert len(formatted) > 0

    def test_format_pattern_failed(self):
        pattern = {
            "trigger": "disk full",
            "action": "clear cache",
            "outcome": "failed",
            "confidence": 0.3,
            "chain_id": "",
            "attempts": 2,
        }
        formatted = self.format_pattern(pattern)
        assert isinstance(formatted, str)

    def test_format_pattern_pending(self):
        pattern = {
            "trigger": "timeout",
            "action": "retry",
            "outcome": "pending",
            "confidence": 0.5,
            "chain_id": "",
            "attempts": 0,
        }
        formatted = self.format_pattern(pattern)
        assert isinstance(formatted, str)


# ============================================================
# memory_quality.py
# ============================================================


class TestMemoryQuality:
    def setup_method(self):
        from shared.memory_quality import QUALITY_THRESHOLD, quality_score

        self.quality_score = quality_score
        self.QUALITY_THRESHOLD = QUALITY_THRESHOLD

    def test_empty_content_zero(self):
        assert self.quality_score("") == 0.0

    def test_short_content_zero(self):
        assert self.quality_score("ok") == 0.0

    def test_high_quality_with_path_and_causal(self):
        content = (
            "Fixed bug in /hooks/shared/state.py line 42 because load_state() "
            "returned None when file was missing"
        )
        score = self.quality_score(content)
        assert score > self.QUALITY_THRESHOLD
        assert score <= 1.0

    def test_file_path_boosts_score(self):
        content_with_path = "Found issue in /home/user/project/main.py needs fix"
        content_without_path = "Found issue in the project file needs fix here today"
        s1 = self.quality_score(content_with_path)
        s2 = self.quality_score(content_without_path)
        assert s1 > s2

    def test_causal_language_boosts_score(self):
        content_causal = "Gate 01 blocked because memory was not queried before edit"
        content_plain = "Gate 01 blocked the operation and would not let it through"
        s1 = self.quality_score(content_causal)
        s2 = self.quality_score(content_plain)
        assert s1 > s2

    def test_error_signal_boosts_score(self):
        content_error = (
            "ImportError Exception in auth module causes crash at startup line 10"
        )
        content_plain = (
            "The auth module has a problem that shows up at startup normally"
        )
        s1 = self.quality_score(content_error)
        s2 = self.quality_score(content_plain)
        assert s1 >= s2

    def test_outcome_signal_boosts_score(self):
        content_outcome = (
            "Fixed auth bug. Outcome: success. Verified by running test suite."
        )
        content_plain = "Fixed auth bug and things work better now and should be fine"
        s1 = self.quality_score(content_outcome)
        s2 = self.quality_score(content_plain)
        assert s1 > s2

    def test_function_call_boosts_score(self):
        content_with_fn = "Call load_state() before save_state() to avoid data loss"
        content_without = "Call the load before save to avoid data loss in sessions"
        s1 = self.quality_score(content_with_fn)
        s2 = self.quality_score(content_without)
        assert s1 >= s2

    def test_score_in_range(self):
        for content in [
            "hello world this is a longer string",
            "Fixed /path/to/file.py because root cause was null pointer. Outcome: success verified.",
            "a" * 1000,
        ]:
            s = self.quality_score(content)
            assert 0.0 <= s <= 1.0, f"Score out of range for: {content[:50]}"

    def test_quality_threshold_defined(self):
        assert 0 < self.QUALITY_THRESHOLD < 1


# ============================================================
# model_profiles.py
# ============================================================


class TestModelProfiles:
    def setup_method(self):
        from shared.model_profiles import (
            AGENT_ROLE_MAP,
            MODEL_PROFILES,
            MODEL_SUGGESTIONS,
            RECOMMENDED_MODELS,
            get_model_for_agent,
        )

        self.AGENT_ROLE_MAP = AGENT_ROLE_MAP
        self.MODEL_PROFILES = MODEL_PROFILES
        self.RECOMMENDED_MODELS = RECOMMENDED_MODELS
        self.MODEL_SUGGESTIONS = MODEL_SUGGESTIONS
        self.get_model_for_agent = get_model_for_agent

    def test_agent_role_map_contains_core_agents(self):
        for agent in ["builder", "plan", "explore", "researcher", "stress-tester"]:
            assert agent in self.AGENT_ROLE_MAP, f"{agent} missing from AGENT_ROLE_MAP"

    def test_agent_roles_valid(self):
        valid_roles = {"planning", "research", "execution", "verification"}
        for agent, role in self.AGENT_ROLE_MAP.items():
            assert role in valid_roles, f"Invalid role {role!r} for {agent}"

    def test_model_profiles_complete(self):
        required = {"quality", "balanced", "efficient", "lean", "budget"}
        for name in required:
            assert name in self.MODEL_PROFILES, f"Profile {name!r} missing"

    def test_each_profile_has_all_roles(self):
        required_roles = {"planning", "research", "execution", "verification"}
        for profile_name, profile in self.MODEL_PROFILES.items():
            role_models = profile["role_models"]
            for role in required_roles:
                assert role in role_models, (
                    f"Profile {profile_name!r} missing role {role!r}"
                )

    def test_profile_models_valid(self):
        valid_models = {"opus", "sonnet", "haiku"}
        for profile_name, profile in self.MODEL_PROFILES.items():
            for role, model in profile["role_models"].items():
                assert model in valid_models, (
                    f"Invalid model {model!r} in {profile_name}/{role}"
                )

    def test_get_model_for_agent_builder_balanced(self):
        model = self.get_model_for_agent("balanced", "builder")
        assert model in ("opus", "sonnet", "haiku")

    def test_get_model_for_agent_unknown_agent(self):
        result = self.get_model_for_agent("balanced", "nonexistent_agent")
        assert result is None

    def test_get_model_for_agent_unknown_profile_fallback(self):
        result = self.get_model_for_agent("nonexistent_profile", "builder")
        assert result is not None  # Falls back to balanced

    def test_get_model_for_agent_quality_planning(self):
        model = self.get_model_for_agent("quality", "plan")
        assert model == "opus"

    def test_get_model_for_agent_budget_research(self):
        model = self.get_model_for_agent("budget", "explore")
        assert model == "haiku"

    def test_recommended_models_all_sets(self):
        for agent, models in self.RECOMMENDED_MODELS.items():
            assert isinstance(models, set)
            for m in models:
                assert m in ("opus", "sonnet", "haiku")

    def test_warn_on_opus_field_present(self):
        for name, profile in self.MODEL_PROFILES.items():
            assert "warn_on_opus" in profile, f"warn_on_opus missing from {name}"
            assert isinstance(profile["warn_on_opus"], bool)


# ============================================================
# search_helpers.py
# ============================================================


class TestSearchHelpers:
    def setup_method(self):
        from shared.search_helpers import (
            detect_query_mode,
            generate_fuzzy_variants,
            merge_results,
        )

        self.detect_query_mode = detect_query_mode
        self.merge_results = merge_results
        self.generate_fuzzy_variants = generate_fuzzy_variants

    def test_detect_tag_query(self):
        assert self.detect_query_mode("tag:type:fix") == "tags"

    def test_detect_tags_prefix(self):
        assert self.detect_query_mode("tags:error") == "tags"

    def test_detect_keyword_quoted(self):
        assert self.detect_query_mode('"exact phrase search"') == "keyword"

    def test_detect_keyword_boolean_and(self):
        assert self.detect_query_mode("foo AND bar") == "keyword"

    def test_detect_keyword_boolean_or(self):
        assert self.detect_query_mode("foo OR bar") == "keyword"

    def test_detect_keyword_short_query(self):
        assert self.detect_query_mode("error") == "keyword"

    def test_detect_keyword_two_words(self):
        assert self.detect_query_mode("import error") == "keyword"

    def test_detect_semantic_question(self):
        assert self.detect_query_mode("how do I fix the rate limiter?") == "semantic"

    def test_detect_semantic_why(self):
        assert self.detect_query_mode("why does gate 01 block edits?") == "semantic"

    def test_detect_semantic_long_query(self):
        result = self.detect_query_mode(
            "memory not being queried before edit operations"
        )
        assert result in ("semantic", "hybrid")

    def test_detect_full_hybrid_routing(self):
        assert self.detect_query_mode("anything", routing="full_hybrid") == "hybrid"

    def test_detect_fast_routing_technical(self):
        result = self.detect_query_mode("fix auth_token", routing="fast")
        assert result == "keyword"

    def test_merge_results_empty(self):
        results = self.merge_results([], [], top_k=10)
        assert results == []

    def test_merge_results_fts_only(self):
        fts = [{"id": "k1", "content": "foo"}, {"id": "k2", "content": "bar"}]
        results = self.merge_results(fts, [], top_k=10)
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert ids == {"k1", "k2"}

    def test_merge_results_lance_only(self):
        lance = [{"id": "k1", "content": "foo"}, {"id": "k2", "content": "bar"}]
        results = self.merge_results([], lance, top_k=10)
        assert len(results) == 2

    def test_merge_results_deduplication(self):
        fts = [{"id": "k1", "content": "foo"}]
        lance = [{"id": "k1", "content": "foo"}]
        results = self.merge_results(fts, lance, top_k=10)
        assert len(results) == 1

    def test_merge_results_both_engines_score_higher(self):
        fts = [{"id": "k1", "content": "foo"}, {"id": "k2", "content": "bar"}]
        lance = [{"id": "k1", "content": "foo"}]
        results = self.merge_results(fts, lance, top_k=10)
        assert results[0]["id"] == "k1"

    def test_merge_results_top_k_respected(self):
        fts = [{"id": f"k{i}", "content": f"entry {i}"} for i in range(10)]
        results = self.merge_results(fts, [], top_k=5)
        assert len(results) <= 5

    def test_merge_results_both_match_label(self):
        fts = [{"id": "k1", "content": "foo"}]
        lance = [{"id": "k1", "content": "foo"}]
        results = self.merge_results(fts, lance, top_k=10)
        assert results[0]["match"] == "both"

    def test_merge_results_relevance_field_set(self):
        fts = [{"id": "k1", "content": "foo"}]
        results = self.merge_results(fts, [], top_k=10)
        assert "relevance" in results[0]
        assert results[0]["relevance"] > 0

    pass  # lance_fts_to_summary tests removed (function removed in SurrealDB migration)

    def test_generate_fuzzy_variants_returns_original(self):
        variants = self.generate_fuzzy_variants("error")
        assert "error" in variants

    def test_generate_fuzzy_variants_deletions(self):
        variants = self.generate_fuzzy_variants("error")
        assert any(len(v) == len("error") - 1 for v in variants if v != "error")

    def test_generate_fuzzy_variants_short_term(self):
        variants = self.generate_fuzzy_variants("ab")
        assert variants == ["ab"]

    def test_generate_fuzzy_variants_is_list(self):
        variants = self.generate_fuzzy_variants("hello")
        assert isinstance(variants, list)
        assert len(variants) > 1


# ============================================================
# tool_profiles.py
# ============================================================


class TestToolProfiles:
    def setup_method(self):
        from shared.tool_profiles import (
            PROFILED_TOOLS,
            add_precondition,
            get_profile,
            get_success_rate,
            get_warnings_for_tool,
            record_failure,
            record_success,
        )

        self.get_profile = get_profile
        self.record_success = record_success
        self.record_failure = record_failure
        self.add_precondition = add_precondition
        self.get_success_rate = get_success_rate
        self.get_warnings_for_tool = get_warnings_for_tool
        self.PROFILED_TOOLS = PROFILED_TOOLS

    def _fresh(self):
        return {}

    def test_get_profile_creates_new(self):
        profiles = self._fresh()
        profile = self.get_profile(profiles, "Edit")
        assert "known_failures" in profile
        assert "preconditions" in profile
        assert "success_count" in profile
        assert "failure_count" in profile
        assert "recent_outcomes" in profile

    def test_get_profile_idempotent(self):
        profiles = self._fresh()
        p1 = self.get_profile(profiles, "Edit")
        p2 = self.get_profile(profiles, "Edit")
        assert p1 is p2

    def test_record_success_increments_counter(self):
        profiles = self._fresh()
        self.record_success(profiles, "Edit", {"file_path": "/foo.py"})
        assert profiles["Edit"]["success_count"] == 1

    def test_record_success_untracked_tool_ignored(self):
        profiles = self._fresh()
        self.record_success(profiles, "UnknownTool", {})
        assert "UnknownTool" not in profiles

    def test_record_failure_increments_counter(self):
        profiles = self._fresh()
        self.record_failure(
            profiles, "Edit", {}, "PermissionError: cannot write to file"
        )
        assert profiles["Edit"]["failure_count"] == 1

    def test_record_failure_new_pattern_returned(self):
        profiles = self._fresh()
        result = self.record_failure(
            profiles, "Edit", {}, "PermissionError: cannot write /etc/passwd"
        )
        assert result is not None
        assert result["is_new"] is True
        assert result["tool"] == "Edit"

    def test_record_failure_duplicate_not_returned(self):
        profiles = self._fresh()
        self.record_failure(
            profiles, "Edit", {}, "PermissionError: cannot write to file"
        )
        result2 = self.record_failure(
            profiles, "Edit", {}, "PermissionError: cannot write to file"
        )
        assert result2 is None

    def test_record_failure_untracked_tool(self):
        profiles = self._fresh()
        result = self.record_failure(profiles, "UnknownTool", {}, "some error")
        assert result is None

    def test_add_precondition_adds_entry(self):
        profiles = self._fresh()
        added = self.add_precondition(
            profiles, "Edit", "File must exist before editing"
        )
        assert added is True
        profile = self.get_profile(profiles, "Edit")
        assert len(profile["preconditions"]) == 1
        assert profile["preconditions"][0]["text"] == "File must exist before editing"

    def test_add_precondition_duplicate_reinforces(self):
        profiles = self._fresh()
        self.add_precondition(profiles, "Edit", "File must exist before editing")
        added2 = self.add_precondition(
            profiles, "Edit", "File must exist before editing"
        )
        assert added2 is False
        profile = self.get_profile(profiles, "Edit")
        assert len(profile["preconditions"]) == 1
        assert profile["preconditions"][0]["reinforced"] == 2

    def test_get_success_rate_no_data(self):
        profile = self.get_profile({}, "Edit")
        rate = self.get_success_rate(profile)
        assert rate == 1.0

    def test_get_success_rate_all_success(self):
        profiles = self._fresh()
        for _ in range(5):
            self.record_success(profiles, "Edit", {})
        rate = self.get_success_rate(profiles["Edit"])
        assert rate == 1.0

    def test_get_success_rate_mixed(self):
        profiles = self._fresh()
        for _ in range(3):
            self.record_success(profiles, "Edit", {})
        self.record_failure(profiles, "Edit", {}, "unique error alpha bravo now")
        rate = self.get_success_rate(profiles["Edit"])
        assert 0 < rate < 1.0

    def test_profiled_tools_contains_core(self):
        for tool in ["Edit", "Write", "Bash", "Read", "Grep"]:
            assert tool in self.PROFILED_TOOLS

    def test_get_warnings_for_tool_empty_profile(self):
        profiles = self._fresh()
        warnings = self.get_warnings_for_tool(
            profiles, "Edit", {"file_path": "/foo.py"}
        )
        assert isinstance(warnings, list)


# ============================================================
# dag_memory.py bridge functions
# ============================================================


@pytest.mark.skip(reason="dag_memory.py removed in SurrealDB migration (Task 14)")
class TestDagMemoryBridge:
    """Test dag_memory.py bridge — fail-open, no external deps required."""

    def setup_method(self):
        from shared.dag_memory import (
            _has_learning_signal,
            _truncate,
            enrich_summary_with_memory,
            get_dag_context_for_chain,
            get_dag_head_tag,
        )

        self._has_learning_signal = _has_learning_signal
        self._truncate = _truncate
        self.enrich_summary_with_memory = enrich_summary_with_memory
        self.get_dag_context_for_chain = get_dag_context_for_chain
        self.get_dag_head_tag = get_dag_head_tag

    def test_has_learning_signal_fix(self):
        assert (
            self._has_learning_signal("fixed the auth bug by adding null check") is True
        )

    def test_has_learning_signal_decision(self):
        assert (
            self._has_learning_signal("decided to use SQLite instead of Redis") is True
        )

    def test_has_learning_signal_correction(self):
        assert (
            self._has_learning_signal("actually the root cause was different") is True
        )

    def test_has_learning_signal_discovery(self):
        assert (
            self._has_learning_signal("discovered that FTS5 is faster than LIKE")
            is True
        )

    def test_has_learning_signal_pattern(self):
        assert self._has_learning_signal("this is an anti-pattern to avoid") is True

    def test_has_learning_signal_no_signal(self):
        assert self._has_learning_signal("hello world, how are you today") is False

    def test_truncate_short(self):
        assert self._truncate("hello", 500) == "hello"

    def test_truncate_long(self):
        result = self._truncate("a" * 1000, 500)
        assert len(result) == 500

    def test_truncate_exact(self):
        result = self._truncate("a" * 500, 500)
        assert len(result) == 500

    def test_get_dag_context_for_chain_fail_open(self):
        result = self.get_dag_context_for_chain()
        assert isinstance(result, dict)

    def test_get_dag_head_tag_fail_open(self):
        result = self.get_dag_head_tag()
        assert isinstance(result, str)

    def test_enrich_summary_fail_open_returns_string(self):
        summary = "This is a test summary about gates and memory"
        result = self.enrich_summary_with_memory(summary)
        assert isinstance(result, str)

    def test_enrich_summary_short_returns_original(self):
        result = self.enrich_summary_with_memory("hi")
        assert result == "hi"

    def test_enrich_summary_preserves_original(self):
        summary = "Gate 01 blocks memory queries before edits"
        result = self.enrich_summary_with_memory(summary)
        assert summary in result


# ============================================================
# dag_memory_layer._infer_tags
# ============================================================


@pytest.mark.skip(reason="dag_memory_layer.py removed in SurrealDB migration (Task 14)")
class TestDagMemoryLayerHelpers:
    """Test private helpers in dag_memory_layer.py."""

    def setup_method(self):
        from shared.dag_memory_layer import _infer_tags

        self._infer_tags = _infer_tags

    def test_infer_tags_fix_assistant(self):
        tags = self._infer_tags(
            "fixed the null pointer bug root cause found", "assistant"
        )
        assert "type:fix" in tags

    def test_infer_tags_decision_assistant(self):
        tags = self._infer_tags(
            "decided to use async approach going with asyncio", "assistant"
        )
        assert "type:decision" in tags

    def test_infer_tags_learning_assistant(self):
        tags = self._infer_tags(
            "turns out FTS5 is much faster than LIKE queries", "assistant"
        )
        assert "type:learning" in tags

    def test_infer_tags_correction_user(self):
        tags = self._infer_tags(
            "actually no that's wrong approach entirely here", "user"
        )
        assert "type:correction" in tags

    def test_infer_tags_feature_request_user(self):
        tags = self._infer_tags("can you add a feature for auto commit here", "user")
        assert "type:feature-request" in tags

    def test_infer_tags_high_priority(self):
        tags = self._infer_tags(
            "this is critical breaking security vulnerability", "assistant"
        )
        assert "priority:high" in tags

    def test_infer_tags_fallback(self):
        tags = self._infer_tags("nothing special here at all today", "assistant")
        assert tags == "type:auto-captured"

    def test_infer_tags_multiple_tags_comma_separated(self):
        tags = self._infer_tags(
            "fixed critical security bug breaking production", "assistant"
        )
        assert "," in tags
