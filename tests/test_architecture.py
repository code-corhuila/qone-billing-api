"""The dependency rule of Annex C, enforced by a test (ADR-007 accepted cost): the arrows point
to the domain. `domain/` imports nothing of the project outside itself and no framework or
driver; `application/` imports the domain and nothing of the adapters; neither imports FastAPI,
Pydantic, psycopg, PyJWT, uvicorn or Starlette."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "billing"
FORBIDDEN = {"fastapi", "starlette", "pydantic", "psycopg", "psycopg_pool", "jwt", "uvicorn", "sqlalchemy", "pika"}


def imports_of(module: Path) -> set[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def modules_under(layer: str) -> list[Path]:
    folder = SRC / layer
    return sorted(folder.rglob("*.py")) if folder.exists() else []


def roots(names: set[str]) -> set[str]:
    return {name.split(".")[0] for name in names}


def test_the_domain_depends_on_nothing_of_the_project_but_itself():
    for module in modules_under("domain"):
        for name in imports_of(module):
            if name.startswith("billing."):
                assert name.startswith("billing.domain"), f"{module.name} imports {name}"


def test_the_application_never_imports_an_adapter():
    for module in modules_under("application"):
        for name in imports_of(module):
            if name.startswith("billing."):
                assert not name.startswith("billing.adapter"), f"{module.name} imports {name}"
                assert not name.startswith("apps"), f"{module.name} imports {name}"


def test_neither_the_domain_nor_the_application_imports_a_framework_or_a_driver():
    for layer in ("domain", "application"):
        for module in modules_under(layer):
            hit = roots(imports_of(module)) & FORBIDDEN
            assert not hit, f"{module.relative_to(SRC)} imports {sorted(hit)}"


def test_the_domain_exists():
    assert (SRC / "domain" / "model" / "invoice.py").exists()
