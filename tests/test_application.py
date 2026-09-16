import time

import pytest

from tests.fakes.fake_engines import FakeEngines
from src.app import App


@pytest.fixture
def app(tmp_path):
    engines = FakeEngines({"Astra": "hello from Astra", "Opus": "hello from Opus"})
    made = App(tmp_path, cwd=str(tmp_path), engines=engines)
    yield made
    made.stop()


def furnish(app):
    app.add_member(name="Marian", kind="human")
    astra = app.add_member(name="Astra", engine="claude")
    opus = app.add_member(name="Opus", engine="claude")
    project = app.add_project("Sinaxa")
    a = app.add_seat(project.id, "Architect", "Design", astra.id)
    b = app.add_seat(project.id, "Reviewer", "Review", opus.id)
    return project, a, b


def wait(app, job):
    for _ in range(100):
        if app.job(job)["done"]:
            return
        time.sleep(.01)
    raise AssertionError("turn did not finish")


def test_message_is_accepted_then_both_team_members_answer(app):
    project, _, _ = furnish(app)
    message, job = app.say(project.id, project.team_session.id, "Hello")
    assert message["author"] == "lead"
    wait(app, job)
    messages = app.state(project.id, project.team_session.id)["messages"]
    assert [m["author_name"] for m in messages] == ["Marian", "Astra", "Opus"]


def test_direct_session_only_calls_its_seat(app):
    project, first, _ = furnish(app)
    direct = project.direct_session(first.id)
    _, job = app.say(project.id, direct.id, "Private")
    wait(app, job)
    assert [m["author_name"] for m in app.state(project.id, direct.id)["messages"]] == ["Marian", "Astra"]


def test_clear_context_keeps_history_and_adds_boundary(app):
    project, _, _ = furnish(app)
    session = project.team_session
    _, job = app.say(project.id, session.id, "Before")
    wait(app, job)
    app.clear_context(project.id, session.id)
    messages = app.state(project.id, session.id)["messages"]
    assert any(m.get("kind") == "boundary" for m in messages)
    assert any(m["text"] == "Before" for m in messages)


def test_close_stops_runtime_but_preserves_logical_state(app):
    project, _, _ = furnish(app)
    app.set_project_open(project.id, False)
    assert app.store.load().project(project.id).state == "closed"
    with pytest.raises(Exception, match="open"):
        app.say(project.id, project.team_session.id, "No")
    app.set_project_open(project.id, True)
    assert app.state(project.id)["status"]["agents"] == []


def test_remove_seat_deletes_direct_history_only(app):
    project, first, second = furnish(app)
    direct = project.direct_session(first.id)
    custom = app.add_session(project.id, "Pair", [first.id, second.id])
    app.store.append(project, direct, {"seq": 1, "text": "private"})
    app.store.append(project, custom, {"seq": 1, "text": "keep"})
    app.remove_seat(project.id, first.id)
    assert not app.store.transcript_path(project, direct) or not __import__('os').path.exists(app.store.transcript_path(project, direct))
    assert app.store.messages(project, custom)[0]["text"] == "keep"


def test_type_templates_are_persisted_and_seed_new_projects(app):
    template = app.add_seat_template(
        role="Analyst", prompt="Find reliable sources", category="general")
    project_type = app.add_project_type(
        name="Research", category="general", seat_templates=[template.id])
    project = app.add_project("Evidence", type_id=project_type.id)

    reloaded = app.store.load()
    made = reloaded.project(project.id)
    assert made.type_id == project_type.id
    assert made.seats[0].template_id == template.id
    assert made.seats[0].occupant is None
