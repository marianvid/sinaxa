import threading
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
    assert messages[0]["author_name"] == "Marian"
    assert {m["author_name"] for m in messages[1:]} == {"Astra", "Opus"}


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


def test_human_seat_participates_without_being_run_as_an_engine(app):
    project, _, _ = furnish(app)
    lead = app.sinaxa.lead
    human = app.add_seat(project.id, "Human lead", "Lead the discussion", lead.id)

    _, job = app.say(project.id, project.team_session.id, "Discuss this")
    wait(app, job)
    messages = app.state(project.id, project.team_session.id)["messages"]
    assert messages[0]["author_name"] == "Marian"
    assert {message["author_name"] for message in messages[1:]} == {
        "Astra", "Opus"}
    assert app.sinaxa.seat_trouble(project, human) is None

    direct = project.direct_session(human.id)
    _, direct_job = app.say(project.id, direct.id, "A private note")
    wait(app, direct_job)
    assert [message["author_name"] for message in
            app.state(project.id, direct.id)["messages"]] == ["Marian"]


def test_mention_is_mandatory_while_other_agents_may_decline(tmp_path):
    engines = FakeEngines({"Astra": "addressed answer",
                           "Opus": "[NO_REPLY]"})
    app = App(tmp_path, cwd=str(tmp_path), engines=engines)
    try:
        project, _, _ = furnish(app)
        _, job = app.say(project.id, project.team_session.id,
                         "@Astra answer this")
        wait(app, job)

        messages = app.state(project.id, project.team_session.id)["messages"]
        assert [message["author_name"] for message in messages] == [
            "Marian", "Astra"]
        assert engines.heard_by("Opus")
        assert "not explicitly mentioned" in engines.heard_by("Opus")[0]
        assert "provider-native" in engines.agents["Astra"].instructions
    finally:
        app.stop()


def test_team_fanout_is_concurrent(tmp_path):
    barrier = threading.Barrier(2)

    def meet(_):
        barrier.wait(timeout=1)
        return "ready"

    engines = FakeEngines({"Astra": meet, "Opus": meet})
    app = App(tmp_path, cwd=str(tmp_path), engines=engines)
    try:
        project, _, _ = furnish(app)
        _, job = app.say(project.id, project.team_session.id, "Start together")
        wait(app, job)
        assert len(app.state(project.id, project.team_session.id)["messages"]) == 3
    finally:
        app.stop()


def test_agent_mentions_are_processed_fifo_without_cursor_regression(tmp_path):
    engines = FakeEngines({
        ("Astra", 1): "@Opus, question from Astra",
        ("Opus", 1): "@Astra, question from Opus",
        ("Opus", 2): "answer to Astra",
        ("Astra", 2): "answer to Opus",
    })
    app = App(tmp_path, cwd=str(tmp_path), engines=engines)
    try:
        project, astra, opus = furnish(app)
        _, job = app.say(project.id, project.team_session.id,
                         "@Astra and @Opus begin")
        wait(app, job)

        messages = app.state(project.id, project.team_session.id)["messages"]
        assert messages[0]["author_name"] == "Marian"
        assert sorted(message["author_name"] for message in messages[1:]) == [
            "Astra", "Astra", "Opus", "Opus"]
        checkpoints = app.store.checkpoints(project, project.team_session)
        assert sorted((checkpoints[astra.id]["delivered"],
                       checkpoints[opus.id]["delivered"])) == [2, 3]
    finally:
        app.stop()


def test_conversation_limits_are_configurable_for_managed_sessions(app):
    project, _, _ = furnish(app)
    session = project.team_session
    app.update_session(project.id, session.id, turn_timeout=3600,
                       max_agent_turns=40)
    loaded = app.store.load().project(project.id).session(session.id)
    assert loaded.turn_timeout == 3600
    assert loaded.max_agent_turns == 40
