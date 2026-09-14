import pytest

from src.model import CLOSED, CUSTOM, DIRECT, TEAM, EngineConfig, ModelError, Sinaxa


def furnished():
    state = Sinaxa(engines=[EngineConfig("claude", "claude")])
    state.add_member(name="Marian", kind="human")
    one = state.add_member(name="Astra", engine="claude")
    two = state.add_member(name="Opus", engine="claude")
    project = state.add_project("Sinaxa", "/tmp")
    return state, project, one, two


def test_seats_create_direct_sessions_and_join_team():
    _, project, one, two = furnished()
    a = project.add_seat("Architect", "Design", one.id)
    b = project.add_seat("Reviewer", "Review", two.id)
    assert project.team_session.participants == [a.id, b.id]
    assert sorted(s.kind for s in project.sessions) == [DIRECT, DIRECT, TEAM]


def test_removing_seat_removes_direct_but_preserves_group_container():
    _, project, one, two = furnished()
    a = project.add_seat("Architect", "Design", one.id)
    b = project.add_seat("Reviewer", "Review", two.id)
    custom = project.add_session("Design review", [a.id, b.id])
    _, direct = project.remove_seat(a.id)
    assert direct not in project.sessions
    assert custom in project.sessions and custom.participants == [b.id]
    assert project.team_session.participants == [b.id]


def test_managed_sessions_cannot_be_deleted():
    _, project, one, _ = furnished()
    seat = project.add_seat("Architect", "Design", one.id)
    with pytest.raises(ModelError):
        project.remove_session(project.direct_session(seat.id).id)
    with pytest.raises(ModelError):
        project.remove_session(project.team_session.id)


def test_custom_session_requires_valid_seats():
    _, project, _, _ = furnished()
    with pytest.raises(ModelError):
        project.add_session("Empty", [])
    with pytest.raises(ModelError):
        project.add_session("Ghost", ["missing"])


def test_global_and_agent_configuration_are_separate():
    state, _, one, _ = furnished()
    engine = state.engine("claude")
    engine.max_concurrency = 8
    one.model, one.effort = "opus", "high"
    assert engine.max_concurrency == 8 and one.model == "opus"


def test_project_state_and_unique_names_are_domain_rules():
    state, project, _, _ = furnished()
    project.state = CLOSED
    assert not project.is_open
    with pytest.raises(ModelError):
        state.add_project("sinaxa")
