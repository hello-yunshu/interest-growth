from __future__ import annotations

import json
from pathlib import Path


def _web_text(project_root: Path) -> str:
    parts = []
    for path in (project_root / "apps/web").rglob("*.js"):
        if any(part in {"node_modules", ".next", "out"} for part in path.parts):
            continue
        if not path.is_file():
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_beautiful_ai_primitives_cover_reference_interactions(project_root):
    ui = (project_root / "apps/web/components/BeautifulUI.js").read_text(encoding="utf-8")
    expected = [
        "PixelLoader", "ActivityTrace", "StreamingText", "ApprovalCard", "ToolChips",
        "TaskRows", "ChatPanel", "PromptBar", "RecommendationCard", "ContextCards",
        "DiffTable", "RecordsTable", "FilterTabs", "InsightCards", "CodeBlock",
        "FineTunePanel", "SelectionActions", "SafeSvgPreview", "GraphView",
    ]
    for name in expected:
        assert f"export function {name}" in ui, name
    shell = (project_root / "apps/web/components/DesktopShell.js").read_text(encoding="utf-8")
    assert "commandPalette" in shell
    assert "sideNavGroup" in shell
    assert "ArrowDown" in shell and "ArrowUp" in shell


def test_ai_native_primitives_are_used_in_real_feature_pages(project_root):
    usage = {
        "ActivityTrace": "apps/web/app/tutor/page.js",
        "ChatPanel": "apps/web/app/tutor/page.js",
        "StreamingText": "apps/web/app/tutor/page.js",
        "ApprovalCard": "apps/web/app/learning/page.js",
        "DiffTable": "apps/web/app/writing/page.js",
        "ContextCards": "apps/web/app/knowledge/page.js",
        "FineTunePanel": "apps/web/app/system/page.js",
        "SafeSvgPreview": "apps/web/app/content/page.js",
        "InsightCards": "apps/web/app/growth/page.js",
        "RecommendationCard": "apps/web/app/curiosity/page.js",
        "TaskRows": "apps/web/app/book/page.js",
        "RecordsTable": "apps/web/app/career/page.js",
        "PromptBar": "apps/web/app/research/page.js",
    }
    for primitive, rel in usage.items():
        assert primitive in (project_root / rel).read_text(encoding="utf-8"), (primitive, rel)


def test_no_legacy_browser_modal_or_raw_html_injection_in_renderer(project_root):
    text = _web_text(project_root)
    for forbidden in ["window.prompt(", "window.confirm(", "window.alert(", "dangerouslySetInnerHTML"]:
        assert forbidden not in text, forbidden


def test_activity_trace_explicitly_excludes_private_reasoning_categories(project_root):
    ui = (project_root / "apps/web/components/BeautifulUI.js").read_text(encoding="utf-8")
    assert "Never render hidden/private model chain-of-thought" in ui
    assert "PRIVATE_TRACE_CATEGORIES" in ui
    assert "PUBLIC_TRACE_CATEGORIES" in ui
    assert "publicEventDetail" in ui
    assert "if (category === 'tool_result')" in ui
    assert "工具已经完成" in ui
    for category in ["thinking", "reasoning", "chain_of_thought", "internal_thought"]:
        assert category in ui
    tutor = (project_root / "apps/web/app/tutor/page.js").read_text(encoding="utf-8")
    assert "ActivityTrace" in tutor
    assert "JSON.stringify(events.filter" not in tutor


def test_graph_view_is_a_real_interactive_surface(project_root):
    ui = (project_root / "apps/web/components/BeautifulUI.js").read_text(encoding="utf-8")
    for marker in [
        "buiGraphCanvas", "viewBox=", "markerEnd", "搜索节点", "缩小关系图",
        "放大关系图", "拖动画布可平移", "只看邻居", "data-graph-node",
    ]:
        assert marker in ui, marker
    css = (project_root / "apps/web/app/globals.css").read_text(encoding="utf-8")
    assert ".buiGraphSvgNode" in css
    assert ".buiGraphCanvas" in css


def test_next16_lint_uses_explicit_eslint_cli(project_root):
    package = json.loads((project_root / "apps/web/package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["lint"].startswith("eslint ")
    assert "next lint" not in package["scripts"]["lint"]
    assert "eslint" in package.get("devDependencies", {})
    assert "eslint-config-next" in package.get("devDependencies", {})
    assert (project_root / "apps/web/eslint.config.mjs").exists()


def test_provider_settings_use_recoverable_backup_write(project_root):
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert 'path.with_extension("json.bak")' in rust
    assert "file.sync_all()" in rust
    assert "for candidate in [&path, &backup]" in rust
    assert "serde_json::from_str::<ProviderSettings>(&raw)" in rust
    assert "std::fs::rename(&path, &backup)" in rust


def test_tauri_renderer_still_cannot_connect_directly_to_providers(project_root):
    conf = json.loads((project_root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    connect = conf["app"]["security"]["csp"].split("connect-src", 1)[1].split(";", 1)[0]
    assert "https://" not in connect
    assert "deepseek" not in connect.lower()
    assert ("deep" + "tutor") not in connect.lower()


def test_research_external_source_links_allow_only_http_https(project_root):
    research = (project_root / "apps/web/app/research/page.js").read_text(encoding="utf-8")
    assert "['http:','https:'].includes(url.protocol)" in research
    assert "href={s.canonical_url}" not in research
    assert "openExternalUrl(safe)" in research
    adapter = (project_root / "apps/web/lib/runtime/platforms/tauri-desktop.js").read_text(encoding="utf-8")
    api = (project_root / "apps/web/lib/api.js").read_text(encoding="utf-8")
    assert "@tauri-apps/plugin-opener" in adapter
    assert "Only HTTP/HTTPS external URLs are allowed." in api


def test_native_export_keeps_user_selected_write_scope_narrow(project_root):
    capability = json.loads((project_root / "apps/desktop/src-tauri/capabilities/default.json").read_text(encoding="utf-8"))
    permissions = set(capability["permissions"])
    assert "dialog:allow-save" in permissions
    assert "fs:allow-write-file" in permissions
    assert "fs:write-all" not in permissions
    adapter = (project_root / "apps/web/lib/runtime/platforms/tauri-desktop.js").read_text(encoding="utf-8")
    assert "@tauri-apps/plugin-dialog" in adapter
    assert "writeFile(destination" in adapter


def test_prompt_bar_does_not_render_fake_tool_controls(project_root):
    ui = (project_root / "apps/web/components/BeautifulUI.js").read_text(encoding="utf-8")
    assert "commands = false" in ui
    assert "onMention && <button" in ui
    assert "onCommand && <button" in ui
    assert 'tabIndex={-1}>@</button>' not in ui


def test_renderer_avoids_nested_interactive_link_buttons(project_root):
    home = (project_root / "apps/web/app/page.js").read_text(encoding="utf-8")
    assert '<Link href="/curiosity"><button' not in home
    assert '<Link href="/learning"><button' not in home
    assert '<Link href="/writing"><button' not in home


def test_tauri_external_sources_open_in_system_browser_with_capability(project_root):
    capability = json.loads((project_root / "apps/desktop/src-tauri/capabilities/default.json").read_text(encoding="utf-8"))
    assert "opener:allow-default-urls" in capability["permissions"]
    cargo = (project_root / "apps/desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    rust = (project_root / "apps/desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    package = json.loads((project_root / "apps/web/package.json").read_text(encoding="utf-8"))
    assert 'tauri-plugin-opener = "2"' in cargo
    assert ".plugin(tauri_plugin_opener::init())" in rust
    assert "@tauri-apps/plugin-opener" in package["dependencies"]
