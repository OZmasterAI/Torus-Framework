"""Tests for Toroidal-Indexer Tier 3: parse_agent_output() and prompt refinement."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "toroidal-indexer")
)

from scripts.ai_pass import (
    EDGE_SCHEMA,
    _pass1_prompt,
    _pass2_prompt,
    _pass3_prompt,
    parse_agent_output,
)


class TestParseAgentOutput:
    def test_valid_json_array(self):
        raw = json.dumps(
            [
                {
                    "source": "main.py:main",
                    "target": "utils.py:helper",
                    "relation": "calls",
                    "confidence": 0.9,
                    "line": 5,
                    "reason": "direct call",
                },
            ]
        )
        result = parse_agent_output(raw)
        assert len(result) == 1
        assert result[0]["source"] == "main.py:main"
        assert result[0]["relation"] == "calls"

    def test_json_in_markdown_fence(self):
        raw = '```json\n[{"source": "a.py:f", "target": "b.py:g", "relation": "imports", "confidence": 0.8, "line": 1, "reason": "import"}]\n```'
        result = parse_agent_output(raw)
        assert len(result) == 1
        assert result[0]["relation"] == "imports"

    def test_json_with_preamble_text(self):
        raw = 'Here are the edges I found:\n\n[{"source": "a.py:f", "target": "b.py:g", "relation": "calls", "confidence": 0.8, "line": 10, "reason": "call"}]\n\nThat covers the main relationships.'
        result = parse_agent_output(raw)
        assert len(result) == 1

    def test_malformed_json_returns_empty(self):
        raw = '[{"source": "a.py:f", "target": "b.py:g", "relation": "calls", BROKEN'
        result = parse_agent_output(raw)
        assert result == []

    def test_empty_response_returns_empty(self):
        assert parse_agent_output("") == []
        assert parse_agent_output("   ") == []

    def test_no_json_at_all(self):
        raw = "I couldn't find any edges in these files."
        result = parse_agent_output(raw)
        assert result == []

    def test_skips_entries_missing_required_fields(self):
        raw = json.dumps(
            [
                {
                    "source": "a.py:f",
                    "target": "b.py:g",
                    "relation": "calls",
                    "confidence": 0.8,
                    "line": 1,
                    "reason": "ok",
                },
                {"source": "a.py:f"},  # missing target, relation
                {"target": "b.py:g", "relation": "calls"},  # missing source
            ]
        )
        result = parse_agent_output(raw)
        assert len(result) == 1

    def test_skips_invalid_relation(self):
        raw = json.dumps(
            [
                {
                    "source": "a.py:f",
                    "target": "b.py:g",
                    "relation": "destroys",
                    "confidence": 0.8,
                    "line": 1,
                    "reason": "nope",
                },
            ]
        )
        result = parse_agent_output(raw)
        assert result == []

    def test_multiple_edges(self):
        edges = [
            {
                "source": f"mod{i}.py:fn{i}",
                "target": f"mod{i + 1}.py:fn{i + 1}",
                "relation": "calls",
                "confidence": 0.8,
                "line": i,
                "reason": "test",
            }
            for i in range(5)
        ]
        result = parse_agent_output(json.dumps(edges))
        assert len(result) == 5

    def test_json_fence_with_language_tag(self):
        raw = '```json\n[{"source": "a.py:x", "target": "b.py:y", "relation": "reads", "confidence": 0.8, "line": 1, "reason": "r"}]\n```'
        result = parse_agent_output(raw)
        assert len(result) == 1

    def test_nested_backticks_extracts_first(self):
        raw = 'Some text\n```json\n[{"source": "a.py:x", "target": "b.py:y", "relation": "writes", "confidence": 0.8, "line": 1, "reason": "w"}]\n```\nMore text\n```json\n[]\n```'
        result = parse_agent_output(raw)
        assert len(result) == 1
        assert result[0]["relation"] == "writes"


class TestEdgeSchema:
    def test_schema_has_required_fields(self):
        required = {"source", "target", "relation"}
        assert required.issubset(set(EDGE_SCHEMA["required"]))

    def test_schema_defines_all_properties(self):
        props = set(EDGE_SCHEMA["properties"].keys())
        assert {
            "source",
            "target",
            "relation",
            "confidence",
            "line",
            "reason",
        }.issubset(props)


class TestPass1Prompt:
    def test_includes_file_list(self):
        files = ["main.py", "utils.py", "config.py"]
        prompt = _pass1_prompt(files, "/project")
        for f in files:
            assert f in prompt

    def test_includes_json_only_instruction(self):
        prompt = _pass1_prompt(["a.py"], "/project")
        assert "ONLY" in prompt
        assert "JSON" in prompt

    def test_includes_example(self):
        prompt = _pass1_prompt(["a.py"], "/project")
        assert "source" in prompt
        assert "target" in prompt
        assert "relation" in prompt


class TestPass2Prompt:
    def test_includes_known_edges(self):
        edges = [{"source": "a.py:f", "target": "b.py:g", "relation": "calls"}]
        prompt = _pass2_prompt(["a.py", "b.py"], edges, "/project")
        assert "a.py:f" in prompt
        assert "implicit" in prompt.lower() or "IMPLICIT" in prompt

    def test_includes_file_list(self):
        prompt = _pass2_prompt(["main.py", "utils.py"], [], "/project")
        assert "main.py" in prompt
        assert "utils.py" in prompt


class TestPass3Prompt:
    def test_receives_graph_summary_not_raw_edges(self):
        summary = {
            "node_count": 50,
            "edge_counts": {"calls": 30, "imports": 20},
            "top_hubs": [{"name": "main.py:main", "degree": 15}],
            "isolated_nodes": ["orphan.py:lonely"],
        }
        prompt = _pass3_prompt(summary, "/project")
        assert "50" in prompt  # node count
        assert "main.py:main" in prompt  # hub node
        assert "orphan.py:lonely" in prompt or "isolated" in prompt.lower()
        assert isinstance(prompt, str)
