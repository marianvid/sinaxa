from pathlib import Path


def test_primary_sections_are_independent_files():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "seats", "types", "engines", "settings"):
        for suffix in (".html", ".css", ".js"):
            assert (ui / (page + suffix)).is_file()


def test_pages_extend_the_original_visual_system():
    ui = Path(__file__).parents[1] / "ui"
    base = (ui / "base.css").read_text()
    assert "--bg:#14161c" in base
    assert "grid-template-columns:262px 1fr" in base
    assert ".brand .mark:after" in base
    for page in ("projects", "members", "seats", "types", "engines"):
        assert "@import url('/base.css')" in (ui / (page + ".css")).read_text()


def test_navigation_links_all_primary_sections():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "seats", "types", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        assert "/projects.html" in html
        assert "/members.html" in html
        assert "/seats.html" in html
        assert "/types.html" in html
        assert "/engines.html" in html
        assert "/settings.html" in html


def test_named_navigation_is_grouped_at_the_top_right():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "seats", "types", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        assert html.index('class="global-header"') < html.index('class="side"')
        assert 'class="global-nav"' in html
        assert 'class="top"' not in html
        for label in ("Chats", "Agents", "Seats", "Types", "Engines", "Settings"):
            assert f'<span>{label}</span>' in html
        assert 'id="themeToggle"' in html
        assert html.index('class="global-nav"') < html.index('class="global-actions"')
        assert html.index('<span>Settings</span>') < html.index('class="global-divider"')
        assert html.index('class="global-divider"') < html.index('id="themeToggle"')


def test_sidebar_is_always_projects_without_seats_or_sessions_sections():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "seats", "types", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        side = html[html.index('class="side"'):html.index('</aside>')]
        assert '>Projects ' in side
        assert 'sidebar-group' not in side
        assert '>Seats<' not in side
        assert '>Sessions<' not in side


def test_status_bar_is_removed_from_every_page():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "seats", "types", "engines", "settings"):
        assert 'statusbar' not in (ui / (page + ".html")).read_text()
    assert '.statusbar' not in (ui / "base.css").read_text()
    assert '.statusbar' not in (ui / "settings.css").read_text()


def test_global_theme_toggle_is_shared_by_every_page():
    ui = Path(__file__).parents[1] / "ui"
    assert (ui / "base.js").is_file()
    base_js = (ui / "base.js").read_text()
    assert "sinaxa-theme" in base_js
    assert '<svg class="theme-icon"' in base_js
    assert "☀" not in base_js and "☾" not in base_js
    for page in ("projects", "members", "seats", "types", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        assert '<script src="/base.js"></script>' in html
    server = (ui.parent / "src" / "server.py").read_text()
    assert 'STATIC["/base.js"]' in server


def test_projects_owns_seats_sessions_search_and_attachments():
    html = (Path(__file__).parents[1] / "ui" / "projects.html").read_text()
    for marker in ('id="seats"', 'id="sessions"', 'id="search"',
                   'id="files"', 'id="toggleProject"'):
        assert marker in html


def test_projects_exposes_non_destructive_clear_context_action():
    ui = Path(__file__).parents[1] / "ui"
    html = (ui / "projects.html").read_text()
    script = (ui / "projects.js").read_text()
    assert 'id="clearContext"' in html
    assert 'id="clearSession"' not in html
    assert "/context" in script
    assert "/history" not in script


def test_projects_exposes_hierarchical_project_navigation_and_overview():
    ui = Path(__file__).parents[1] / "ui"
    html = (ui / "projects.html").read_text()
    script = (ui / "projects.js").read_text()
    assert 'id="projectOverview"' in html
    assert 'id="openMain"' in html
    assert "Direct sessions" not in script
    assert 'class="roster-line' in script
    assert 'data-open-session' in script
    assert "Main team" in html


def test_projects_loads_transcript_history_progressively():
    script = (Path(__file__).parents[1] / "ui" / "projects.js").read_text()
    assert "loadOlder" in script
    assert "before:String(transcript[0].seq)" in script
    assert "Scroll up to load earlier messages" in script
