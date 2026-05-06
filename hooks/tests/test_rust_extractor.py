"""Tests for shared/extractors/rust_extractor.py — regex-based Rust extraction (~70% coverage)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestExtractsUseStatements:
    """test_extracts_use_statements: use crate::, use super::, use self::, use std::"""

    def test_use_crate(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("use crate::consensus::validator;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1
        assert any("consensus::validator" in e.target for e in import_edges)

    def test_use_super(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        sub = tmp_path / "sub"
        sub.mkdir()
        rs = sub / "child.rs"
        rs.write_text("use super::parent_mod;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1
        assert any("parent_mod" in e.target for e in import_edges)

    def test_use_self(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("use self::inner::Thing;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1
        assert any("inner::Thing" in e.target for e in import_edges)

    def test_use_external_crate(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("use serde::Deserialize;\nuse tokio::runtime;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        # External crate imports should still be captured
        assert len(import_edges) >= 2

    def test_use_braced_group(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("use crate::config::{Settings, Database};\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1

    def test_use_line_numbers_correct(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("// comment\nuse crate::foo;\nuse crate::bar;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = sorted(
            [e for e in edges if e.relation == "imports"], key=lambda e: e.source_line
        )
        assert import_edges[0].source_line == 2
        assert import_edges[1].source_line == 3


class TestExtractsModDeclarations:
    """test_extracts_mod_declarations: mod foo; and mod foo { ... }"""

    def test_mod_declaration(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("mod config;\nmod utils;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        mod_names = [e.target for e in import_edges]
        assert any("config" in t for t in mod_names)
        assert any("utils" in t for t in mod_names)

    def test_pub_mod_declaration(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("pub mod api;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1
        assert any("api" in e.target for e in import_edges)

    def test_mod_resolves_to_file(self, tmp_path):
        """mod foo should resolve to foo.rs if it exists."""
        from shared.extractors.rust_extractor import extract_rust

        (tmp_path / "config.rs").write_text("pub fn load() {}\n")
        rs = tmp_path / "lib.rs"
        rs.write_text("mod config;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert any("config.rs" in e.target for e in import_edges)

    def test_mod_resolves_to_dir(self, tmp_path):
        """mod foo should resolve to foo/mod.rs if foo.rs does not exist."""
        from shared.extractors.rust_extractor import extract_rust

        sub = tmp_path / "config"
        sub.mkdir()
        (sub / "mod.rs").write_text("pub fn load() {}\n")
        rs = tmp_path / "lib.rs"
        rs.write_text("mod config;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert any(
            "config/mod.rs" in e.target or "config" in e.target for e in import_edges
        )


class TestExtractsImplBlocks:
    """test_extracts_impl_blocks: impl Foo, impl Trait for Foo"""

    def test_impl_for_struct(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text(
            "struct Validator {}\nimpl Validator {\n    fn validate(&self) {}\n}\n"
        )
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        impl_edges = [e for e in edges if e.relation == "implements"]
        assert len(impl_edges) >= 1

    def test_impl_trait_for_struct(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text(
            "trait Runnable { fn run(&self); }\n"
            "struct Worker {}\n"
            "impl Runnable for Worker {\n    fn run(&self) {}\n}\n"
        )
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        impl_edges = [e for e in edges if e.relation == "implements"]
        assert len(impl_edges) >= 1
        assert any("Runnable" in e.target for e in impl_edges)
        assert any("Worker" in e.source for e in impl_edges)


class TestExtractsPubUseReexports:
    """test_extracts_pub_use_reexports: pub use crate::..."""

    def test_pub_use_reexport(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("pub use crate::config::Settings;\npub use crate::db::Pool;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 2
        # All pub use should have confidence 1.0
        assert all(e.confidence == 1.0 for e in import_edges)

    def test_pub_use_external(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("pub use serde_json::Value;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1


class TestExtractsFunctionDefinitions:
    """test_extracts_function_definitions: fn, pub fn, pub(crate) fn, async fn"""

    def test_pub_fn(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text(
            "pub fn process_request(req: Request) -> Response {\n    todo!()\n}\n"
        )
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        fn_nodes = [n for n in nodes if n.type == "function"]
        assert any(n.name == "process_request" for n in fn_nodes)

    def test_private_fn(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("fn helper() -> bool {\n    true\n}\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        fn_nodes = [n for n in nodes if n.type == "function"]
        assert any(n.name == "helper" for n in fn_nodes)

    def test_pub_crate_fn(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("pub(crate) fn internal_api() {}\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        fn_nodes = [n for n in nodes if n.type == "function"]
        assert any(n.name == "internal_api" for n in fn_nodes)

    def test_async_fn(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text(
            "pub async fn fetch_data() -> Result<Data, Error> {\n    todo!()\n}\n"
        )
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        fn_nodes = [n for n in nodes if n.type == "function"]
        assert any(n.name == "fetch_data" for n in fn_nodes)

    def test_fn_line_numbers(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("// header\n\npub fn alpha() {}\nfn beta() {}\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        fn_nodes = sorted(
            [n for n in nodes if n.type == "function"], key=lambda n: n.line
        )
        assert fn_nodes[0].name == "alpha"
        assert fn_nodes[0].line == 3
        assert fn_nodes[1].name == "beta"
        assert fn_nodes[1].line == 4

    def test_file_node_always_present(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("fn main() {}\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        file_nodes = [n for n in nodes if n.type == "file"]
        assert len(file_nodes) == 1
        assert "lib.rs" in file_nodes[0].file


class TestResolvesCratePathsViaCargoToml:
    """test_resolves_crate_paths_via_cargo_toml: workspace member resolution"""

    def test_workspace_member_resolution(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        # Set up a workspace Cargo.toml
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text(
            '[workspace]\nmembers = [\n    "crates/torus-consensus",\n    "crates/torus-network",\n]\n'
        )
        # Create the crate source
        crate_src = tmp_path / "crates" / "torus-consensus" / "src"
        crate_src.mkdir(parents=True)
        (crate_src / "validator.rs").write_text("pub fn validate() {}\n")

        # Create a Cargo.toml in the crate with package name
        crate_cargo = tmp_path / "crates" / "torus-consensus" / "Cargo.toml"
        crate_cargo.write_text('[package]\nname = "torus-consensus"\n')

        # Source file that imports from the crate
        src = tmp_path / "crates" / "torus-consensus" / "src"
        rs = src / "lib.rs"
        rs.write_text("use crate::validator;\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1

    def test_no_cargo_toml_still_works(self, tmp_path):
        """Extractor should work even without a Cargo.toml."""
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("use crate::some_module;\nfn main() {}\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        # Should not crash, and should still extract what it can
        assert len(nodes) >= 1  # at least the file node
        import_edges = [e for e in edges if e.relation == "imports"]
        assert len(import_edges) >= 1


class TestHandlesParseErrorGracefully:
    """test_handles_parse_error_gracefully: binary files, encoding errors, missing files"""

    def test_binary_file(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "binary.rs"
        rs.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        # Should return empty, not crash
        assert isinstance(nodes, list)
        assert isinstance(edges, list)

    def test_missing_file(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        nodes, edges = extract_rust(str(tmp_path / "nonexistent.rs"), str(tmp_path))
        assert nodes == []
        assert edges == []

    def test_empty_file(self, tmp_path):
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "empty.rs"
        rs.write_text("")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        # File node should still be present
        file_nodes = [n for n in nodes if n.type == "file"]
        assert len(file_nodes) == 1


class TestSkipsCfgConditionalImports:
    """test_skips_cfg_conditional_imports: #[cfg(...)] items are included but not evaluated."""

    def test_cfg_use_still_extracted(self, tmp_path):
        """Items behind #[cfg] are included (known limitation: not evaluated)."""
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text(
            '#[cfg(feature = "metrics")]\nuse crate::metrics::Counter;\n\n'
            "#[cfg(test)]\nmod tests;\n\n"
            "use crate::config::Settings;\n"
        )
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        # All three should be extracted (cfg not evaluated, by design)
        targets = " ".join(e.target for e in import_edges)
        assert "metrics" in targets
        assert "tests" in targets or any("tests" in e.target for e in import_edges)
        assert "Settings" in targets or "config" in targets

    def test_cfg_test_mod_extracted(self, tmp_path):
        """#[cfg(test)] mod tests should be extracted even though conditional."""
        from shared.extractors.rust_extractor import extract_rust

        rs = tmp_path / "lib.rs"
        rs.write_text("#[cfg(test)]\nmod tests {\n    use super::*;\n}\n")
        nodes, edges = extract_rust(str(rs), str(tmp_path))
        import_edges = [e for e in edges if e.relation == "imports"]
        # At least the "mod tests" should be found
        assert any("tests" in e.target for e in import_edges)
