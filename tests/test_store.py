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
