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
    architect = app.sinaxa.seat_template("seat_architect")
    reviewer = app.add_seat_template(role="Reviewer", prompt="Review")
    a = app.add_seat(project.id, architect.id, astra.id)
    b = app.add_seat(project.id, reviewer.id, opus.id)
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
    assert all("requires your visible answer" in app._fixed_engines.heard_by(name)[0]
               for name in ("Astra", "Opus"))


def test_agent_replies_remain_unread_until_the_session_end_is_marked(app):
    project, _, _ = furnish(app)
    session = project.team_session
    _, job = app.say(project.id, session.id, "Hello")
    wait(app, job)

    state = app.state(project.id, session.id)
    listed = next(item for item in state["projects"][0]["sessions"]
                  if item["id"] == session.id)
    assert listed["unread"] == 2
    assert session.read_seq == 0

    assert app.mark_read(project.id, session.id, session.seq) == session.seq
    assert session.unread_count == 0
    loaded = app.store.load().project(project.id).session(session.id)
    assert loaded.read_seq == session.seq
    assert loaded.unread_count == 0


def test_direct_session_only_calls_its_seat(app):
    project, first, _ = furnish(app)
    direct = project.direct_session(first.id)
    _, job = app.say(project.id, direct.id, "Private")
    wait(app, job)
    assert [m["author_name"] for m in app.state(project.id, direct.id)["messages"]] == ["Marian", "Astra"]
    assert "requires your visible answer" in app._fixed_engines.heard_by("Astra")[0]


def test_clear_context_keeps_history_and_adds_boundary(app):
    project, _, _ = furnish(app)
    session = project.team_session
    _, job = app.say(project.id, session.id, "Before")
    wait(app, job)
    app.clear_context(project.id, session.id)
    messages = app.state(project.id, session.id)["messages"]
    assert any(m.get("kind") == "boundary" for m in messages)
    assert any(m["text"] == "Before" for m in messages)
    boundary = next(m for m in messages if m.get("kind") == "boundary")
    assert "remain in the transcript" in boundary["text"]
    assert boundary["meta"]["boundary"] == "context_clear"


def test_clear_closed_history_keeps_the_active_context(app):
    project, _, _ = furnish(app)
    session = project.team_session
    _, old_job = app.say(project.id, session.id, "Old context")
    wait(app, old_job)
    app.clear_context(project.id, session.id)
    _, active_job = app.say(project.id, session.id, "Active context")
    wait(app, active_job)
    active_start = session.context_start_seq
    last_seq = session.seq

    result = app.clear_context_history(project.id, session.id)

    messages = app.store.messages(project, session)
    assert result["removed"] > 0
    assert all(message["seq"] >= active_start for message in messages)
    assert any(message["text"] == "Active context" for message in messages)
    assert session.context_start_seq == active_start
    assert session.seq == last_seq


def test_native_compaction_is_visible_but_does_not_clear_team_context(tmp_path):
    engines = FakeEngines({"Astra": (
        "after compaction", {"compacted": True,
                             "compaction": {"trigger": "auto"}}),
        "Opus": "[NO_REPLY]"})
    made = App(tmp_path, cwd=str(tmp_path), engines=engines)
    try:
        project, _, _ = furnish(made)
        _, job = made.say(project.id, project.team_session.id, "Long turn")
        wait(made, job)
        messages = made.state(project.id, project.team_session.id)["messages"]
        marker = next(m for m in messages if m.get("kind") == "compaction")
        assert marker["text"] == "Astra compacted native context (auto)"
        assert project.team_session.context_start_seq == 0
    finally:
        made.stop()


def test_clear_session_removes_history_but_keeps_configuration(app):
    project, _, _ = furnish(app)
    session = project.team_session
    app.update_session(project.id, session.id, turn_timeout=3600,
                       max_agent_turns=80)
    app.store.append(project, session, {"seq": 1, "text": "remove me"})
    session.seq = 1

    app.clear_history(project.id, session.id)

    assert app.store.messages(project, session) == []
    assert session.seq == 0
    assert session.turn_timeout == 3600
    assert session.max_agent_turns == 80


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
    template = app.add_seat_template(
        role="Human lead", prompt="Lead the discussion")
    human = app.add_seat(project.id, template.id, lead.id)

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


def test_human_mentions_limit_replies_and_preserve_later_awareness(tmp_path):
    engines = FakeEngines({"Astra": "addressed answer",
                           "Opus": "later answer"})
    app = App(tmp_path, cwd=str(tmp_path), engines=engines)
    try:
        project, _, _ = furnish(app)
        _, job = app.say(project.id, project.team_session.id,
                         "@Astra answer this")
        wait(app, job)

        messages = app.state(project.id, project.team_session.id)["messages"]
        assert [message["author_name"] for message in messages] == [
            "Marian", "Astra"]
        assert not engines.heard_by("Opus")

        direct = project.direct_session(project.seats[1].id)
        _, direct_job = app.say(project.id, direct.id, "Private follow-up")
        wait(app, direct_job)
        assert "@Astra answer this" in engines.heard_by("Opus")[0]
        assert "addressed answer" in engines.heard_by("Opus")[0]
        assert "provider-native" in engines.agents["Astra"].instructions
        instructions = " ".join(
            engines.agents["Astra"].instructions.split())
        assert "context only and never invites your response" in instructions
        assert "Use all available project knowledge" in instructions
        assert "visibility controls disclosure" in instructions.casefold()
        assert "necessary to complete the human lead's current request" in (
            instructions)
        assert "sufficient authorization" in instructions
        assert "never repeat them" in engines.agents["Astra"].instructions
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
        checkpoints = app.store.agent_contexts(project)
        astra_cursor = checkpoints[astra.occupant]["delivered"][
            project.team_session.id]
        opus_cursor = checkpoints[opus.occupant]["delivered"][
            project.team_session.id]
        assert sorted((astra_cursor, opus_cursor)) == [4, 5]
    finally:
        app.stop()


def test_one_agent_process_shares_main_and_direct_context(app):
    project, astra, _ = furnish(app)
    direct = project.direct_session(astra.id)

    _, first_job = app.say(project.id, direct.id, "Private fact: code is 47")
    wait(app, first_job)
    _, second_job = app.say(project.id, project.team_session.id,
                            "@Astra what was the private fact?")
    wait(app, second_job)

    astra_agents = [agent for agent in app._fixed_engines.history
                    if agent.name == "Astra"]
    assert len(astra_agents) == 1
    assert "[Architect · private] Marian: Private fact: code is 47" in (
        astra_agents[0].heard[0])
    assert "@Astra what was the private fact?" in astra_agents[0].heard[1]


def test_direct_activation_does_not_replay_main_already_in_native_context(app):
    project, astra, _ = furnish(app)
    _, main_job = app.say(project.id, project.team_session.id,
                          "@Astra remember this team fact")
    wait(app, main_job)

    direct = project.direct_session(astra.id)
    _, direct_job = app.say(project.id, direct.id, "What do you remember?")
    wait(app, direct_job)

    last_prompt = app._fixed_engines.heard_by("Astra")[-1]
    assert "remember this team fact" not in last_prompt
    assert "hello from Astra" not in last_prompt
    assert "What do you remember?" in last_prompt


def test_conversation_limits_are_configurable_for_managed_sessions(app):
    project, _, _ = furnish(app)
    session = project.team_session
    app.update_session(project.id, session.id, turn_timeout=3600,
                       max_agent_turns=40)
    loaded = app.store.load().project(project.id).session(session.id)
    assert loaded.turn_timeout == 3600
    assert loaded.max_agent_turns == 40


def test_non_persistent_engine_mode_is_rejected(app):
    with pytest.raises(Exception, match="not yet implemented"):
        app.update_engine("claude", mode="resume")
