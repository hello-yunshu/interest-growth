#!/usr/bin/env python3
"""Unit tests for scripts/ci/resolve_desktop_app_binary.py (prompt §7 / §8 / §21)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import resolve_desktop_app_binary as resolver  # noqa: E402

CARGO_TOML = """\
[package]
name = "interest-growth-desktop"
version = "1.0.0"
edition = "2021"

[lib]
name = "interest_growth_desktop_lib"
crate-type = ["staticlib", "cdylib", "rlib"]
"""

TAURI_CONF = """\
{
  "productName": "Interest Growth",
  "version": "1.0.0",
  "identifier": "app.psychologygrowth.desktop"
}
"""


def make_repo(tmp: Path) -> Path:
    src_tauri = tmp / "apps" / "desktop" / "src-tauri"
    (src_tauri / "binaries").mkdir(parents=True)
    (src_tauri / "Cargo.toml").write_text(CARGO_TOML, encoding="utf-8")
    (src_tauri / "tauri.conf.json").write_text(TAURI_CONF, encoding="utf-8")
    return tmp


def release_dir(tmp: Path, triple: str) -> Path:
    d = tmp / "apps" / "desktop" / "src-tauri" / "target" / triple / "release"
    d.mkdir(parents=True)
    return d


class ResolveDesktopAppBinaryTest(unittest.TestCase):
    def test_cargo_package_name(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            self.assertEqual(
                resolver.cargo_package_name(repo / "apps/desktop/src-tauri/Cargo.toml"),
                "interest-growth-desktop",
            )

    def test_win_deterministic_path_wins_over_helpers(self):
        # primary exists alongside build-script-* and sidecar and a renamed
        # legacy exe — deterministic candidate must win.
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "x86_64-pc-windows-msvc")
            (rel / "interest-growth-desktop.exe").write_bytes(b"")
            (rel / "build-script-build.exe").write_bytes(b"")
            (rel / "psychology-growth-core-x86_64.exe").write_bytes(b"")
            (rel / "interest-growth.exe").write_bytes(b"")
            got = resolver.resolve(repo, "x86_64-pc-windows-msvc")
            self.assertEqual(got.name, "interest-growth-desktop.exe")

    def test_win_rejects_build_script_only(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "x86_64-pc-windows-msvc")
            (rel / "build-script-build.exe").write_bytes(b"")
            with self.assertRaises(LookupError):
                resolver.resolve(repo, "x86_64-pc-windows-msvc")

    def test_win_rejects_sidecar_only(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "x86_64-pc-windows-msvc")
            (rel / "psychology-growth-core-x86_64.exe").write_bytes(b"")
            with self.assertRaises(LookupError):
                resolver.resolve(repo, "x86_64-pc-windows-msvc")

    def test_win_rejects_dll(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "x86_64-pc-windows-msvc")
            (rel / "webview2loader.dll").write_bytes(b"")
            with self.assertRaises(LookupError):
                resolver.resolve(repo, "x86_64-pc-windows-msvc")

    def test_win_ambiguity_fails(self):
        # No primary; two non-rejected exes -> ambiguity must FAIL, never head -1.
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "x86_64-pc-windows-msvc")
            (rel / "some-helper.exe").write_bytes(b"")
            (rel / "another-helper.exe").write_bytes(b"")
            with self.assertRaises(RuntimeError) as ctx:
                resolver.resolve(repo, "x86_64-pc-windows-msvc")
            self.assertIn("ambiguous", str(ctx.exception))

    def test_win_not_found_fails(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            release_dir(repo, "x86_64-pc-windows-msvc")
            with self.assertRaises(LookupError):
                resolver.resolve(repo, "x86_64-pc-windows-msvc")

    def test_mac_deterministic_bundle_executable(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "aarch64-apple-darwin")
            exe_dir = rel / "bundle" / "macos" / "Interest Growth.app" / "Contents" / "MacOS"
            exe_dir.mkdir(parents=True)
            (exe_dir / "interest-growth-desktop").write_bytes(b"")
            os.chmod(exe_dir / "interest-growth-desktop", 0o755)
            # sidecar inside the bundle must never be picked instead.
            (exe_dir / "psychology-growth-core-aarch64-apple-darwin").write_bytes(b"")
            os.chmod(exe_dir / "psychology-growth-core-aarch64-apple-darwin", 0o755)
            got = resolver.resolve(repo, "aarch64-apple-darwin")
            self.assertEqual(got.name, "interest-growth-desktop")
            self.assertIn("Interest Growth.app", str(got))

    def test_mac_sidecar_only_in_bundle_fails(self):
        # bundle present but only sidecar inside -> primary missing, .app dir is
        # skipped, no other release candidates -> FAIL (sidecar never main).
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "aarch64-apple-darwin")
            exe_dir = rel / "bundle" / "macos" / "Interest Growth.app" / "Contents" / "MacOS"
            exe_dir.mkdir(parents=True)
            (exe_dir / "psychology-growth-core-aarch64-apple-darwin").write_bytes(b"")
            os.chmod(exe_dir / "psychology-growth-core-aarch64-apple-darwin", 0o755)
            with self.assertRaises(LookupError):
                resolver.resolve(repo, "aarch64-apple-darwin")

    def test_mac_fallback_unique_binary(self):
        # No .app bundle but exactly one un-rejected plain binary in release/.
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            rel = release_dir(repo, "aarch64-apple-darwin")
            (rel / "interest-growth-desktop").write_bytes(b"")
            os.chmod(rel / "interest-growth-desktop", 0o755)
            got = resolver.resolve(repo, "aarch64-apple-darwin")
            self.assertEqual(got.name, "interest-growth-desktop")


if __name__ == "__main__":
    unittest.main()
