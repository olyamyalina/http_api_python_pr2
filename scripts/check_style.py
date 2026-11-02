"""Enforce the repository and code rules listed on assignment page five."""

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

from radon.complexity import cc_visit

ROOT = Path(__file__).resolve().parents[1]
MAX_LINES = 1000
MAX_WIDTH = 80
MAX_FUNCTION_LINES = 40
MAX_ARGUMENTS = 7
MAX_COMPLEXITY = 10
EXIT_FAILURE = 1
EXIT_SUCCESS = 0
FIRST_LINE = 1
REQUIRED_PATHS = ("README.md", ".gitignore", "src", "tests")
LAUNCHERS = ("run.sh", "run.bat", "Makefile")
FORBIDDEN_PARTS = {
    ".venv", "__pycache__", ".pytest_cache", ".hypothesis", ".ruff_cache",
    ".idea", ".vscode", "build", "dist", "output", "htmlcov",
}
FORBIDDEN_SUFFIXES = {
    ".zip", ".7z", ".rar", ".tar", ".gz", ".whl", ".pdf", ".png",
    ".jpg", ".jpeg", ".exe", ".dll", ".pyc", ".pyo", ".db", ".sqlite",
}
COMMIT_PATTERN = re.compile(
    r"^[a-z]+(?:\([a-z0-9_-]+\))?!?: .+"
)


def git(*arguments):
    """Inspect this repository without changing global Git configuration."""
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *arguments],
        cwd=ROOT, capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8")


def repository_errors():
    """Check required paths and Conventional Commits in local history."""
    errors = [f"Missing {name}" for name in REQUIRED_PATHS
              if not (ROOT / name).exists()]
    if not any((ROOT / name).is_file() for name in LAUNCHERS):
        errors.append("Missing run.sh, run.bat or Makefile")
    for subject in git("log", "--format=%s").splitlines():
        if not COMMIT_PATTERN.fullmatch(subject):
            errors.append(f"Invalid commit subject: {subject}")
    tracked = git("ls-files", "-z").split("\0")
    for name in filter(None, tracked):
        errors.extend(tracked_file_errors(name))
    return errors


def tracked_file_errors(name):
    """Reject archives, binaries, caches and editor/build output in Git."""
    path = Path(name)
    errors = []
    if set(path.parts) & FORBIDDEN_PARTS:
        errors.append(f"Tracked generated/editor file: {name}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        errors.append(f"Tracked binary/archive file: {name}")
    if path.name == ".coverage" or any(
        part.endswith(".egg-info") for part in path.parts
    ):
        errors.append(f"Tracked Python/build metadata: {name}")
    if b"\0" in (ROOT / path).read_bytes():
        errors.append(f"Tracked binary content: {name}")
    return errors


def function_errors(node):
    """Count all declared arguments and physical lines including decorators."""
    errors = []
    starts = [node.lineno, *(item.lineno for item in node.decorator_list)]
    if node.end_lineno - min(starts) + FIRST_LINE > MAX_FUNCTION_LINES:
        errors.append(
            f"Function {node.name} exceeds {MAX_FUNCTION_LINES} lines"
        )
    args = node.args
    count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    count += bool(args.vararg) + bool(args.kwarg)
    if count > MAX_ARGUMENTS:
        errors.append(f"Function {node.name} exceeds {MAX_ARGUMENTS} arguments")
    return errors


def ast_errors(tree):
    """Reject long functions and numeric literals anywhere in comparisons."""
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            errors.extend(function_errors(node))
        if isinstance(node, ast.Compare) and has_numeric_literal(node):
            errors.append(f"Line {node.lineno}: numeric literal in comparison")
    return errors


def has_numeric_literal(node):
    """Include tuple members, negative values and arithmetic operands."""
    return any(isinstance(child, ast.Constant)
               and type(child.value) in (int, float, complex)
               for child in ast.walk(node))


def complexity_blocks(source):
    """Visit methods and nested closures as well as top-level functions."""
    pending = list(cc_visit(source))
    while pending:
        block = pending.pop()
        yield block
        pending.extend(getattr(block, "methods", ()))
        pending.extend(getattr(block, "closures", ()))


def source_errors(path):
    """Check physical limits, comments, comparisons and Radon complexity."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    errors = []
    if len(lines) > MAX_LINES:
        errors.append(f"File exceeds {MAX_LINES} lines")
    errors.extend(f"Line {index}: exceeds {MAX_WIDTH} characters"
                  for index, line in enumerate(lines, FIRST_LINE)
                  if len(line) > MAX_WIDTH)
    errors.extend(ast_errors(ast.parse(source)))
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    errors.extend(f"Line {token.start[0]}: comment outside docstring"
                  for token in tokens if token.type == tokenize.COMMENT)
    errors.extend(f"{block.name}: complexity {block.complexity}"
                  for block in complexity_blocks(source)
                  if block.complexity > MAX_COMPLEXITY)
    return [f"{path.relative_to(ROOT)}: {error}" for error in errors]


def lint_errors():
    """Run PEP 8, naming, undefined-name and McCabe checks."""
    commands = (
        ["ruff", "check", "src", "tests", "scripts"],
        ["pycodestyle", "src", "tests", "scripts", "--max-line-length=80"],
    )
    errors = []
    for command in commands:
        result = subprocess.run([sys.executable, "-m", *command], cwd=ROOT)
        if result.returncode:
            errors.append(f"Linter failed: {command[0]}")
    return errors


def main():
    """Fail the shared check command when any assignment rule is violated."""
    errors = repository_errors()
    paths = sorted(path for folder in ("src", "tests", "scripts")
                   for path in (ROOT / folder).rglob("*.py"))
    for path in paths:
        errors.extend(source_errors(path))
    errors.extend(lint_errors())
    for error in errors:
        print(error)
    if errors:
        return EXIT_FAILURE
    print(f"Style audit passed: {len(paths)} Python files; all local rules.")
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
