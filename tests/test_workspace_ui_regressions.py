def test_fixed_sidebar_keeps_workspace_in_the_content_column(project_root):
    css = (project_root / "apps/web/app/globals.css").read_text(encoding="utf-8")
    assert ".workspace{grid-column:2;" in css
    assert "@media(max-width:760px){.workspace{grid-column:auto}" in css


def test_claim_outputs_follow_the_nested_claim_contract(project_root):
    data = (project_root / "apps/web/lib/workspaceData.js").read_text(encoding="utf-8")
    route = (project_root / "apps/api/pg_api/routes/research.py").read_text(encoding="utf-8")
    assert 'claims.append({"claim":' in route
    assert "export function normalizeClaimRecord" in data
    assert "row.claim || row" in data
    assert "row.current_version || {}" in data
    assert "const claim = normalizeClaimRecord(row)" in data


def test_global_search_queries_real_local_content(project_root):
    shell = (project_root / "apps/web/components/DesktopShell.js").read_text(encoding="utf-8")
    assert "api('/questions?limit=100')" in shell
    assert "api('/notes')" in shell
    assert "api('/sources')" in shell
    assert "当前兴趣中的页面与内容" in shell


def test_year_heatmap_uses_52_weeks_and_has_an_accessible_summary(project_root):
    widgets = (project_root / "apps/web/components/WorkspaceWidgets.js").read_text(encoding="utf-8")
    css = (project_root / "apps/web/app/globals.css").read_text(encoding="utf-8")
    assert "buildHeatmap(data.timeline, 52)" in widgets
    assert "过去 52 周共留下" in widgets
    assert "repeat(52,10px)" in css


def test_empty_workspace_layout_and_keyboard_editing_are_supported(project_root):
    layout = (project_root / "apps/web/lib/workspaceLayout.js").read_text(encoding="utf-8")
    widgets = (project_root / "apps/web/components/WorkspaceWidgets.js").read_text(encoding="utf-8")
    assert "Array.isArray(value) ? value : defaults" in layout
    assert "moveBy(index, -1)" in widgets
    assert "moveBy(index, 1)" in widgets
    assert "aria-pressed={mode === 'continue'}" in widgets
    assert "event.key === 'Escape'" in widgets
    assert "returnFocusRef.current?.focus?.()" in widgets


def test_no_numbered_legacy_web_source_copies_remain(project_root):
    web = project_root / "apps/web"
    assert not [path for path in web.rglob("* 2.js") if "node_modules" not in path.parts]
