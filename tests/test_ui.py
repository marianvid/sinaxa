from pathlib import Path


def test_four_sections_are_independent_files():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "engines", "settings"):
        for suffix in (".html", ".css", ".js"):
            assert (ui / (page + suffix)).is_file()


def test_navigation_has_no_separate_seats_page():
    ui = Path(__file__).parents[1] / "ui"
    for page in ("projects", "members", "engines", "settings"):
        html = (ui / (page + ".html")).read_text()
        assert "/seats.html" not in html
        assert "/engines.html" in html


def test_projects_owns_seats_sessions_search_and_attachments():
    html = (Path(__file__).parents[1] / "ui" / "projects.html").read_text()
    for marker in ('id="seats"', 'id="sessions"', 'id="search"',
                   'id="files"', 'id="toggleProject"'):
        assert marker in html
