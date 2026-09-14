import json
import os

from src.model import EngineConfig, Sinaxa
from src.store import Store


def test_round_trip_and_atomic_files(tmp_path):
    store = Store(tmp_path)
    state = Sinaxa(engines=[EngineConfig("claude", "claude")])
    lead = state.add_member(name="Marian", kind="human")
    project = state.add_project("Sinaxa", str(tmp_path))
    project.add_seat("Lead", "Lead", lead.id)
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
