import json
import os

from src.model import EngineConfig, Sinaxa
from src.store import Store


def test_round_trip_and_atomic_files(tmp_path):
    store = Store(tmp_path)
    state = Sinaxa(engines=[EngineConfig("claude", "claude")])
    lead = state.add_member(name="Marian", kind="human")
    project = state.add_project("Sinaxa", str(tmp_path))
    template = state.add_seat_template(role="Lead", prompt="Lead")
    state.add_project_seat(project.id, template.id, lead.id)
    store.save_all(state)
    loaded = store.load()
    assert loaded.projects[0].team_session.participants
    assert not list(tmp_path.rglob(".sinaxa-*"))


def test_transcript_checkpoint_storage_and_clear(tmp_path):
    store = Store(tmp_path)
    state = Sinaxa(engines=[EngineConfig("claude", "claude")])
    project = state.add_project("P")
    session = project.team_session
    store.append(project, session, {"seq": 1, "text": "hello"})
    store.save_checkpoint(project, session, "seat", {"native_id": "abc"})
    assert store.messages(project, session)[0]["text"] == "hello"
    assert store.checkpoints(project, session)["seat"]["native_id"] == "abc"
    assert store.storage(project) > 0
    store.clear_history(project, session)
    assert store.messages(project, session) == []


def test_project_agent_context_tracks_each_session_cursor(tmp_path):
    store = Store(tmp_path)
    project = Sinaxa().add_project("P")
    store.save_agent_context(project, "member", {
        "native_id": "native", "engine": "claude",
        "delivered": {"main": 12, "direct": 4}})

    checkpoint = store.agent_contexts(project)["member"]
    assert checkpoint["native_id"] == "native"
    assert checkpoint["delivered"] == {"main": 12, "direct": 4}

    store.forget_agent_session(project, "direct")
    assert store.agent_contexts(project)["member"]["delivered"] == {"main": 12}


def test_closed_context_history_can_be_deleted_one_section_at_a_time(tmp_path):
    store = Store(tmp_path)
    project = Sinaxa().add_project("P")
    session = project.team_session
    messages = [
        {"seq": 1, "text": "old one"},
        {"seq": 2, "text": "old two"},
        {"seq": 3, "kind": "boundary", "text": "Context cleared — old",
         "meta": {"boundary": "context_clear"}},
        {"seq": 4, "text": "middle"},
        {"seq": 5, "kind": "boundary", "text": "Context cleared — middle",
         "meta": {"boundary": "context_clear"}},
        {"seq": 6, "text": "active"},
    ]
    for message in messages:
        store.append(project, session, message)

    result = store.clear_context_history(project, session, boundary_seq=5)
    assert result["removed"] == 2
    assert [m["seq"] for m in store.messages(project, session)] == [1, 2, 3, 6]

    result = store.clear_context_history(project, session)
    assert result["removed"] == 3
    assert [m["seq"] for m in store.messages(project, session)] == [6]


def test_history_cleanup_removes_only_orphaned_attachments(tmp_path):
    store = Store(tmp_path)
    project = Sinaxa().add_project("P")
    session = project.team_session
    old = store.save_image(project, session, b"old", ".png")
    shared = store.save_image(project, session, b"shared", ".png")
    store.append(project, session, {"seq": 1, "text": "old",
                                        "images": [old, shared]})
    store.append(project, session, {"seq": 2, "kind": "boundary",
                                        "text": "Context cleared",
                                        "meta": {"boundary": "context_clear"}})
    store.append(project, session, {"seq": 3, "text": "active",
                                        "images": [shared]})

    result = store.clear_context_history(project, session)

    assert result["attachments"] == 1
    assert store.image_path(project, session, old) is None
    assert store.image_path(project, session, shared)


def test_transcript_pages_return_recent_messages_then_older_windows(tmp_path):
    store = Store(tmp_path)
    state = Sinaxa(engines=[EngineConfig("claude", "claude")])
    project = state.add_project("P")
    session = project.team_session
    for seq in range(1, 151):
        store.append(project, session, {"seq": seq, "text": "message %d" % seq})

    latest = store.message_page(project, session, limit=60)
    older = store.message_page(
        project, session, before=latest["oldest_seq"], limit=60)
    oldest = store.message_page(
        project, session, before=older["oldest_seq"], limit=60)

    assert [m["seq"] for m in latest["messages"]] == list(range(91, 151))
    assert [m["seq"] for m in older["messages"]] == list(range(31, 91))
    assert [m["seq"] for m in oldest["messages"]] == list(range(1, 31))
    assert latest["has_more"] and older["has_more"]
    assert not oldest["has_more"]


def test_transcript_search_is_filtered_before_it_is_paged(tmp_path):
    store = Store(tmp_path)
    project = Sinaxa().add_project("P")
    session = project.team_session
    for seq in range(1, 21):
        text = "match" if seq % 2 == 0 else "other"
        store.append(project, session, {"seq": seq, "text": text})
    page = store.message_page(project, session, limit=4, search="MATCH")
    assert [m["seq"] for m in page["messages"]] == [14, 16, 18, 20]
    assert page["has_more"]


def test_erasing_is_scoped_to_sinaxa_project(tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("safe")
    store = Store(tmp_path / "state")
    state = Sinaxa(engines=[EngineConfig("claude", "claude")])
    project = state.add_project("P")
    store.save_project(project)
    store.erase_project(project)
    assert outside.read_text() == "safe"


def test_new_store_includes_minimum_viable_catalogs(tmp_path):
    state = Store(tmp_path).load()
    assert {item.id for item in state.project_types} >= {
        "type_blank", "type_software"}
    assert {item.id for item in state.seat_templates} >= {
        "seat_architect", "seat_developer", "seat_tester"}


def test_legacy_project_seats_are_migrated_into_the_global_catalog(tmp_path):
    store = Store(tmp_path)
    project = {
        "id": "prj_legacy", "name": "Legacy", "cwd": str(tmp_path),
        "state": "open", "type_id": "type_blank",
        "seats": [{"id": "seat_old", "role": "Legacy analyst",
                   "prompt": "Analyse", "occupant": None,
                   "template_id": None}],
        "sessions": []}
    store._write("projects/prj_legacy/project.json", project)

    state = store.load()

    seat = state.projects[0].seats[0]
    assert seat.template_id
    assert state.seat_template(seat.template_id).role == "Legacy analyst"
    persisted = json.loads(
        (tmp_path / "projects/prj_legacy/project.json").read_text())
    assert persisted["seats"][0]["template_id"] == seat.template_id
