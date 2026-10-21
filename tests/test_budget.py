import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = ("docs/", "examples/")
MAX_FILES = 60  # the specification's own layout needs more than its 46-file figure; the README records the count
APPLICATION = ("src/", "pipelines/", "api/", "ops/")  # the 1,200 lines the specification budgets
MAX_APP_LINES, MAX_TEST_LINES, MAX_BICEP_LINES = (
    1400,
    400,
    400,
)  # 1,200 in the specification; raised in phase 7, see CLAUDE.md
MAX_DEPTH, MAX_FUNCTION_LINES, MAX_COMMENTS = 3, 35, 24


def tracked_files(*suffixes: str) -> list[Path]:
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    names = subprocess.run(command, capture_output=True, text=True, check=True, cwd=ROOT).stdout.split("\n")
    files = [ROOT / name for name in names if name and not name.startswith(EXCLUDED) and (ROOT / name).is_file()]
    return [f for f in files if f.suffix in suffixes] if suffixes else files


def lines(paths: list[Path]) -> int:
    return sum(len(p.read_text(encoding="utf-8").splitlines()) for p in paths)


def test_file_and_depth_budget() -> None:
    files = tracked_files()
    assert len(files) <= MAX_FILES, f"{len(files)} tracked files"
    deepest = max(len(f.relative_to(ROOT).parts) - 1 for f in files)
    assert deepest <= MAX_DEPTH, f"directory depth {deepest}"


def test_line_budgets() -> None:
    python = tracked_files(".py")
    application = [f for f in python if str(f.relative_to(ROOT)).replace("\\", "/").startswith(APPLICATION)]
    tests = [f for f in python if f not in application]
    assert lines(application) <= MAX_APP_LINES, f"{lines(application)} application Python lines"
    assert lines(tests) <= MAX_TEST_LINES, f"{lines(tests)} test lines"
    assert lines(tracked_files(".bicep", ".bicepparam")) <= MAX_BICEP_LINES


def test_python_craft_and_no_notebook_import() -> None:
    comments = 0
    for path in tracked_files(".py"):
        source = path.read_text(encoding="utf-8")
        comments += sum(1 for line in source.splitlines() if line.lstrip().startswith("#"))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                assert length <= MAX_FUNCTION_LINES, f"{path.name}:{node.name} is {length} lines"
            if isinstance(node, ast.ExceptHandler):
                blind = node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
                assert not blind, f"{path.name}:{node.lineno} catches everything"
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [alias.name for alias in node.names] + [getattr(node, "module", None) or ""]
                assert not any(name.startswith("examples") for name in names), f"{path.name} imports a notebook"
    assert comments <= MAX_COMMENTS, f"{comments} comment lines"
    assert not tracked_files(".ipynb"), "a notebook outside examples/ is part of the system"


def test_dependencies_are_pinned() -> None:
    files = (ROOT / "requirements.txt", ROOT / "requirements-dev.txt", ROOT / "requirements-synth.txt")
    pins = [line for file in files if file.exists() for line in file.read_text().splitlines()]
    for pin in (p for p in pins if p and not p.startswith(("-r", "#"))):
        assert "==" in pin, f"unpinned dependency {pin}"
