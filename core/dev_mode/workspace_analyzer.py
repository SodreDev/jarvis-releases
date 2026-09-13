# core/dev_mode/workspace_analyzer.py — Análise estática de workspace/projeto.
#
# Lê a estrutura de um projeto no disco e extrai contexto relevante
# para injetar nos prompts de desenvolvimento enviados ao Copilot.

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Resultado da análise ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkspaceContext:
    """Contexto imutável extraído de um projeto para injeção em prompts."""
    project_name: str
    root_path: str
    language: str
    framework: str
    structure: str                       # representação em árvore (max 3 níveis)
    dependencies: tuple[str, ...]        # nomes das dependências detectadas
    important_dirs: tuple[str, ...]      # pastas relevantes (src, lib, tests …)
    config_files: tuple[str, ...]        # arquivos de configuração encontrados

    def to_prompt_section(self) -> str:
        """Formata o contexto como bloco de texto pronto para inserir em prompt."""
        lines = [
            f"Project: {self.project_name}",
            f"Language: {self.language}",
        ]
        if self.framework:
            lines.append(f"Framework: {self.framework}")
        if self.important_dirs:
            lines.append(f"Key directories: {', '.join(self.important_dirs)}")
        if self.dependencies:
            # Limita a 30 para não estourar contexto
            deps = self.dependencies[:30]
            extra = len(self.dependencies) - 30
            deps_str = ", ".join(deps)
            if extra > 0:
                deps_str += f" (+{extra} more)"
            lines.append(f"Dependencies: {deps_str}")
        if self.config_files:
            lines.append(f"Config files: {', '.join(self.config_files)}")
        lines.append("")
        lines.append("Project structure:")
        lines.append(self.structure)
        return "\n".join(lines)


# ── Constantes internas ───────────────────────────────────────────────────────

_IGNORE_DIRS: frozenset[str] = frozenset({
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "venv", ".venv", "env", ".env",
    "dist", "build", "out", "target",
    ".idea", ".vscode", ".vs",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "coverage", "htmlcov", ".eggs", "*.egg-info",
})

_IGNORE_FILES: frozenset[str] = frozenset({
    ".DS_Store", "Thumbs.db", "desktop.ini",
})

_LANG_EXTENSIONS: dict[str, str] = {
    ".py": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".c": "C", ".h": "C",
    ".swift": "Swift",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".lua": "Lua",
    ".dart": "Dart",
    ".r": "R", ".R": "R",
    ".scala": "Scala",
    ".ex": "Elixir", ".exs": "Elixir",
}

_LANG_INDICATORS: dict[str, str] = {
    "requirements.txt": "Python", "setup.py": "Python", "pyproject.toml": "Python",
    "Pipfile": "Python", "setup.cfg": "Python",
    "package.json": "JavaScript",
    "tsconfig.json": "TypeScript",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java", "build.gradle": "Java", "build.gradle.kts": "Kotlin",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "pubspec.yaml": "Dart",
    "mix.exs": "Elixir",
    "Package.swift": "Swift",
    "CMakeLists.txt": "C++",
    "Makefile": "C",
}

_FRAMEWORK_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "Python": [
        ("Django", re.compile(r"\bdjango\b", re.I)),
        ("Flask", re.compile(r"\bflask\b", re.I)),
        ("FastAPI", re.compile(r"\bfastapi\b", re.I)),
        ("Streamlit", re.compile(r"\bstreamlit\b", re.I)),
        ("PyTorch", re.compile(r"\btorch\b", re.I)),
        ("TensorFlow", re.compile(r"\btensorflow\b", re.I)),
    ],
    "JavaScript": [
        ("React", re.compile(r"\breact\b", re.I)),
        ("Next.js", re.compile(r"\bnext\b", re.I)),
        ("Vue", re.compile(r"\bvue\b", re.I)),
        ("Angular", re.compile(r"\b@angular/core\b", re.I)),
        ("Express", re.compile(r"\bexpress\b", re.I)),
        ("Nest.js", re.compile(r"\b@nestjs/core\b", re.I)),
    ],
    "TypeScript": [
        ("React", re.compile(r"\breact\b", re.I)),
        ("Next.js", re.compile(r"\bnext\b", re.I)),
        ("Angular", re.compile(r"\b@angular/core\b", re.I)),
        ("Nest.js", re.compile(r"\b@nestjs/core\b", re.I)),
    ],
    "Rust": [
        ("Actix", re.compile(r"\bactix-web\b", re.I)),
        ("Rocket", re.compile(r"\brocket\b", re.I)),
        ("Tokio", re.compile(r"\btokio\b", re.I)),
    ],
    "Go": [
        ("Gin", re.compile(r"\bgin-gonic\b", re.I)),
        ("Echo", re.compile(r"\becho\b", re.I)),
        ("Fiber", re.compile(r"\bgofiber\b", re.I)),
    ],
}

_CONFIG_FILENAMES: frozenset[str] = frozenset({
    "package.json", "tsconfig.json", "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "Pipfile", "Cargo.toml", "go.mod", "go.sum",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "pubspec.yaml", "mix.exs",
    ".eslintrc.json", ".eslintrc.js", ".prettierrc",
    "webpack.config.js", "vite.config.ts", "vite.config.js",
    "jest.config.js", "jest.config.ts", "vitest.config.ts",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", "Makefile", "CMakeLists.txt",
    "tox.ini", "mypy.ini", ".flake8", "ruff.toml",
    "tailwind.config.js", "tailwind.config.ts",
    "next.config.js", "next.config.mjs",
    ".gitignore", "LICENSE", "README.md",
})

_IMPORTANT_DIRNAMES: frozenset[str] = frozenset({
    "src", "lib", "app", "apps", "pkg", "packages",
    "tests", "test", "__tests__", "spec", "specs",
    "core", "api", "server", "client",
    "components", "pages", "views", "routes", "controllers",
    "models", "schemas", "services", "utils", "helpers",
    "config", "configs", "migrations", "scripts",
    "public", "static", "assets", "templates",
    "cmd", "internal", "handlers",
    "comandos", "classifiers", "security",   # Jarvis-specific
})


# ── Funções privadas ──────────────────────────────────────────────────────────

def _should_ignore(name: str) -> bool:
    """Verifica se um diretório ou arquivo deve ser ignorado."""
    if name in _IGNORE_DIRS or name in _IGNORE_FILES:
        return True
    if name.startswith(".") and name not in (".env.example",):
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def _build_tree(root: Path, max_depth: int = 3, _prefix: str = "", _depth: int = 0) -> str:
    """Constrói representação em árvore (max_depth níveis)."""
    if _depth >= max_depth:
        return ""

    lines: list[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return ""

    visible = [e for e in entries if not _should_ignore(e.name)]
    # Limita entradas por nível para não gerar árvores gigantes
    max_entries = 40 if _depth == 0 else 25
    truncated = len(visible) > max_entries
    visible = visible[:max_entries]

    for i, entry in enumerate(visible):
        is_last = (i == len(visible) - 1) and not truncated
        connector = "└── " if is_last else "├── "
        name = entry.name + ("/" if entry.is_dir() else "")
        lines.append(f"{_prefix}{connector}{name}")

        if entry.is_dir():
            extension = "    " if is_last else "│   "
            subtree = _build_tree(entry, max_depth, _prefix + extension, _depth + 1)
            if subtree:
                lines.append(subtree)

    if truncated:
        lines.append(f"{_prefix}└── ... ({len(entries) - max_entries} more)")

    return "\n".join(lines)


def _detect_language(root: Path) -> str:
    """Detecta linguagem principal por arquivos indicadores + contagem de extensões."""
    # Primeiro: checa arquivos indicadores (mais confiável)
    for name, lang in _LANG_INDICATORS.items():
        if (root / name).exists():
            return lang

    # Segundo: conta extensões nos 2 primeiros níveis
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Respeita limites de profundidade
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > 2:
            dirnames.clear()
            continue
        # Ignora diretórios indesejados
        dirnames[:] = [d for d in dirnames if not _should_ignore(d)]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in _LANG_EXTENSIONS:
                lang = _LANG_EXTENSIONS[ext]
                counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        return "Unknown"
    return max(counts, key=counts.get)


def _detect_framework(root: Path, language: str) -> str:
    """Detecta framework principal lendo arquivos de dependência."""
    patterns = _FRAMEWORK_PATTERNS.get(language, [])
    if not patterns:
        return ""

    # Coleta texto dos arquivos de dependência relevantes
    dep_files = {
        "Python": ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"),
        "JavaScript": ("package.json",),
        "TypeScript": ("package.json",),
        "Rust": ("Cargo.toml",),
        "Go": ("go.mod",),
    }
    texts: list[str] = []
    for fname in dep_files.get(language, ()):
        fpath = root / fname
        if fpath.is_file():
            try:
                texts.append(fpath.read_text(encoding="utf-8", errors="ignore")[:8192])
            except OSError:
                pass

    combined = "\n".join(texts)
    for fwname, regex in patterns:
        if regex.search(combined):
            return fwname
    return ""


def _read_dependencies(root: Path, language: str) -> tuple[str, ...]:
    """Lê e retorna lista de dependências do projeto."""
    deps: list[str] = []

    if language == "Python":
        # requirements.txt
        req = root / "requirements.txt"
        if req.is_file():
            try:
                for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        # Extrai nome sem versão
                        name = re.split(r"[>=<!\[;]", line)[0].strip()
                        if name:
                            deps.append(name)
            except OSError:
                pass
        # pyproject.toml — seção [project] dependencies
        pyp = root / "pyproject.toml"
        if pyp.is_file() and not deps:
            try:
                content = pyp.read_text(encoding="utf-8", errors="ignore")
                in_deps = False
                for line in content.splitlines():
                    if re.match(r"^dependencies\s*=\s*\[", line):
                        in_deps = True
                        continue
                    if in_deps:
                        if line.strip().startswith("]"):
                            break
                        m = re.search(r'"([^"]+)"', line)
                        if m:
                            name = re.split(r"[>=<!\[;]", m.group(1))[0].strip()
                            if name:
                                deps.append(name)
            except OSError:
                pass

    elif language in ("JavaScript", "TypeScript"):
        pkg = root / "package.json"
        if pkg.is_file():
            try:
                import json
                data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
                for section in ("dependencies", "devDependencies"):
                    if section in data and isinstance(data[section], dict):
                        deps.extend(data[section].keys())
            except (OSError, json.JSONDecodeError):
                pass

    elif language == "Rust":
        cargo = root / "Cargo.toml"
        if cargo.is_file():
            try:
                in_deps = False
                for line in cargo.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if re.match(r"^\[dependencies\]", line):
                        in_deps = True
                        continue
                    if in_deps:
                        if line.startswith("["):
                            break
                        m = re.match(r"^(\w[\w-]*)\s*=", line)
                        if m:
                            deps.append(m.group(1))
            except OSError:
                pass

    elif language == "Go":
        gomod = root / "go.mod"
        if gomod.is_file():
            try:
                in_req = False
                for line in gomod.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.strip() == "require (":
                        in_req = True
                        continue
                    if in_req:
                        if line.strip() == ")":
                            break
                        parts = line.strip().split()
                        if parts:
                            deps.append(parts[0])
            except OSError:
                pass

    # Deduplica preservando ordem
    seen: set[str] = set()
    unique: list[str] = []
    for d in deps:
        dl = d.lower()
        if dl not in seen:
            seen.add(dl)
            unique.append(d)
    return tuple(unique)


def _find_important_dirs(root: Path) -> tuple[str, ...]:
    """Encontra diretórios relevantes no primeiro nível do projeto."""
    found: list[str] = []
    try:
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and entry.name in _IMPORTANT_DIRNAMES:
                found.append(entry.name)
    except PermissionError:
        pass
    return tuple(found)


def _find_config_files(root: Path) -> tuple[str, ...]:
    """Encontra arquivos de configuração na raiz do projeto."""
    found: list[str] = []
    try:
        for entry in sorted(root.iterdir()):
            if entry.is_file() and entry.name in _CONFIG_FILENAMES:
                found.append(entry.name)
    except PermissionError:
        pass
    return tuple(found)


# ── API pública ───────────────────────────────────────────────────────────────

def analyze_workspace(project_path: str) -> WorkspaceContext:
    """Analisa um projeto e retorna WorkspaceContext com todas as informações relevantes.

    Args:
        project_path: Caminho absoluto para a raiz do projeto.

    Returns:
        WorkspaceContext preenchido, ou com campos padrão se o caminho for inválido.
    """
    root = Path(project_path)
    if not root.is_dir():
        return WorkspaceContext(
            project_name=root.name,
            root_path=str(root),
            language="Unknown",
            framework="",
            structure="(diretório não encontrado)",
            dependencies=(),
            important_dirs=(),
            config_files=(),
        )

    language = _detect_language(root)
    return WorkspaceContext(
        project_name=root.name,
        root_path=str(root),
        language=language,
        framework=_detect_framework(root, language),
        structure=_build_tree(root),
        dependencies=_read_dependencies(root, language),
        important_dirs=_find_important_dirs(root),
        config_files=_find_config_files(root),
    )
