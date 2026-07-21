import ast
from pathlib import Path


WORKSPACE_MODULE = Path(__file__).parents[2] / "app" / "modules" / "workspace"


def test_business_modules_do_not_issue_queries_outside_repositories() -> None:
    offenders = []
    for path in WORKSPACE_MODULE.glob("*.py"):
        if path.name == "repository.py":
            continue
        if "select(" in path.read_text():
            offenders.append(path.name)

    assert offenders == []


def test_every_repository_select_is_scoped_by_a_where_clause() -> None:
    repository_path = WORKSPACE_MODULE / "repository.py"
    tree = ast.parse(repository_path.read_text())
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    unscoped_lines: list[int] = []

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "select"
        ):
            continue

        current = node
        while current in parents:
            current = parents[current]
            if (
                isinstance(current, ast.Call)
                and isinstance(current.func, ast.Attribute)
                and current.func.attr == "where"
            ):
                break
        else:
            unscoped_lines.append(node.lineno)

    assert unscoped_lines == []
