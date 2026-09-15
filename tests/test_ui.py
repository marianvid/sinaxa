from pathlib import Path


def test_four_sections_are_independent_files():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "engines", "settings"):
        for suffix in (".html", ".css", ".js"):
            assert (ui / (page + suffix)).is_file()


def test_pages_extend_the_original_visual_system():
    ui = Path(__file__).parents[1] / "ui"
    base = (ui / "base.css").read_text()
    assert "--bg:#14161c" in base
    assert "grid-template-columns:262px 1fr" in base
    assert ".brand .mark:after" in base
    for page in ("projects", "members", "engines"):
        assert "@import url('/base.css')" in (ui / (page + ".css")).read_text()


def test_navigation_has_no_separate_seats_page():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        assert "/seats.html" not in html
        assert "/engines.html" in html


def test_navigation_is_icon_only_in_a_global_header():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        assert html.index('class="global-header"') < html.index('class="side"')
        assert 'class="global-nav"' in html
        assert 'class="top"' not in html
        for label in ("Projects", "Engines", "Settings"):
            assert f'title="{label}" aria-label="{label}"' in html
            assert f'</i>{label}</a>' not in html
        assert 'title="Agents &amp; seats" aria-label="Agents &amp; seats"' in html
        assert 'id="themeToggle"' in html
        assert html.index('class="global-actions"') < html.index('title="Settings"')


def test_global_theme_toggle_is_shared_by_every_page():
    ui = Path(__file__).parents[1] / "ui"
    assert (ui / "base.js").is_file()
    assert "sinaxa-theme" in (ui / "base.js").read_text()
    for page in ("projects", "members", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        assert '<script src="/base.js"></script>' in html
    server = (ui.parent / "src" / "server.py").read_text()
    assert 'STATIC["/base.js"]' in server


def test_projects_owns_seats_sessions_search_and_attachments():
    html = (Path(__file__).parents[1] / "ui" / "projects.html").read_text()
    for marker in ('id="seats"', 'id="sessions"', 'id="search"',
                   'id="files"', 'id="toggleProject"'):
        assert marker in html
