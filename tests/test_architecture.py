import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / "src"


def production_modules():
    return [path for path in ROOT.rglob("*.py")
            if "__pycache__" not in path.parts]


def test_one_primary_class_per_module():
    exceptions = {ROOT / "engines" / "claude_errors.py"}
    for path in production_modules():
        if path in exceptions:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        classes = [node.name for node in tree.body
                   if isinstance(node, ast.ClassDef)]
        assert len(classes) <= 1, "%s defines %s" % (path, classes)


def test_domain_does_not_import_outer_layers():
    forbidden = {"app", "conversation", "engines", "runtime", "server",
                 "store", "talk"}
    for path in (ROOT / "domain").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0]
                                for alias in node.names)
        assert not (imported & forbidden), "%s imports %s" % (
            path, sorted(imported & forbidden))


def test_persistence_and_conversation_concerns_have_dedicated_modules():
    expected = (
        "persistence/json_documents.py",
        "persistence/project_repository.py",
        "persistence/transcript_repository.py",
        "persistence/agent_context_repository.py",
        "persistence/attachment_store.py",
        "conversation/prompt_builder.py",
        "conversation/context_assembler.py",
        "conversation/routing_policy.py",
        "services/catalog_service.py",
        "services/read_model.py",
        "ports/transcript_repository.py",
        "ports/agent_context_repository.py",
        "ports/project_repository.py",
    )
    assert all((ROOT / relative).is_file() for relative in expected)
