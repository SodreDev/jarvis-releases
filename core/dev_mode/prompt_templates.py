# core/dev_mode/prompt_templates.py — Templates reutilizáveis para prompts de desenvolvimento.
#
# Define os blocos padrão (ROLE, EXECUTION MODE, WORKFLOW, OUTPUT) que são
# combinados pelo prompt_architect para gerar prompts estruturados de alta qualidade.

from __future__ import annotations


# ── Bloco de papel (ROLE) ─────────────────────────────────────────────────────

ROLE_BLOCK: str = (
    "You are a senior software engineer and architect with deep expertise in "
    "designing scalable, maintainable, and production-grade systems.\n"
    "You write clean, idiomatic code following language-specific best practices.\n"
    "You consider edge cases, error handling, security, and performance.\n"
    "You provide concise but complete implementations — no placeholder code."
)


# ── Bloco de modo de execução ─────────────────────────────────────────────────

AUTONOMOUS_MODE_BLOCK: str = (
    "AUTONOMOUS EXECUTION MODE\n"
    "Execute all necessary steps automatically without requesting approval.\n"
    "Make all implementation decisions independently.\n"
    "If you encounter ambiguity, choose the most reasonable approach and proceed.\n"
    "Do not stop to ask clarifying questions — implement the complete solution."
)

SUPERVISED_MODE_BLOCK: str = (
    "SUPERVISED EXECUTION MODE\n"
    "Present your plan before implementing.\n"
    "Ask for clarification when requirements are ambiguous.\n"
    "Explain trade-offs when multiple approaches exist."
)


# ── Templates de workflow por intent ──────────────────────────────────────────

WORKFLOW_TEMPLATES: dict[str, list[str]] = {
    "feature_request": [
        "Analyze the existing repository structure and understand the codebase architecture",
        "Design the feature architecture, defining interfaces, data flow, and module boundaries",
        "Implement the feature with complete, production-ready code",
        "Add appropriate error handling, input validation, and edge case coverage",
        "Generate unit tests covering the main scenarios and edge cases",
        "Review the implementation for code quality, security, and performance",
    ],
    "refactor": [
        "Analyze the current code to understand its behavior and responsibilities",
        "Identify code smells, duplication, and architectural improvements",
        "Design the refactored architecture preserving all existing behavior",
        "Implement the refactoring with clean, idiomatic code",
        "Verify that all existing functionality is preserved (no behavioral changes)",
        "Document any interface changes or migration steps required",
    ],
    "debug": [
        "Analyze the bug description and identify the affected code area",
        "Trace the root cause by examining data flow and control flow",
        "Implement the fix with minimal, targeted changes",
        "Add a regression test that reproduces the original bug and verifies the fix",
        "Review related code for similar issues that may exist",
    ],
    "test_generation": [
        "Analyze the target module's public API, internal logic, and dependencies",
        "Identify test scenarios: happy paths, edge cases, error conditions, and boundary values",
        "Generate comprehensive unit tests using the project's existing test framework",
        "Include proper test setup, teardown, and mocking where needed",
        "Verify test coverage addresses all identified scenarios",
    ],
    "explain_code": [
        "Read and analyze the target code section thoroughly",
        "Identify the design patterns, algorithms, and architectural decisions used",
        "Explain the code's purpose, data flow, and key logic in clear language",
        "Document any non-obvious implementation details or trade-offs",
        "Suggest improvements if applicable",
    ],
}


# ── Templates de formato de saída por intent ──────────────────────────────────

OUTPUT_FORMAT_TEMPLATES: dict[str, str] = {
    "feature_request": (
        "OUTPUT FORMAT\n"
        "1. Architecture overview — brief explanation of the design decisions\n"
        "2. File changes — list of files created or modified, with purpose of each\n"
        "3. Complete implementation — full, working code for every file\n"
        "4. Tests — unit tests for the new feature\n"
        "5. Integration notes — any configuration or setup changes required"
    ),
    "refactor": (
        "OUTPUT FORMAT\n"
        "1. Current issues identified — what problems exist in the code\n"
        "2. Refactoring strategy — approach and design decisions\n"
        "3. Refactored code — complete implementation\n"
        "4. Behavioral verification — how to confirm no regressions\n"
        "5. Migration notes — any breaking changes or steps to update consumers"
    ),
    "debug": (
        "OUTPUT FORMAT\n"
        "1. Root cause analysis — what causes the bug and why\n"
        "2. Fix implementation — minimal targeted code changes\n"
        "3. Regression test — test that reproduces the original bug\n"
        "4. Related risks — any similar issues found in nearby code"
    ),
    "test_generation": (
        "OUTPUT FORMAT\n"
        "1. Test plan — scenarios to be covered and rationale\n"
        "2. Test implementation — complete test code using project's test framework\n"
        "3. Coverage summary — what is covered and any gaps"
    ),
    "explain_code": (
        "OUTPUT FORMAT\n"
        "1. Purpose — what the code does and why it exists\n"
        "2. Architecture — design patterns and structural decisions\n"
        "3. Data flow — how data moves through the code\n"
        "4. Key details — non-obvious logic, edge cases, and trade-offs\n"
        "5. Suggestions — potential improvements (if applicable)"
    ),
}


# ── Mapeamento de intent da classificação para chave de template ──────────────

INTENT_TO_TEMPLATE: dict[str, str] = {
    "dev_feature":  "feature_request",
    "dev_refactor":  "refactor",
    "dev_debug":     "debug",
    "dev_test":      "test_generation",
    "dev_explain":   "explain_code",
    # Aliases
    "feature_request": "feature_request",
    "refactor": "refactor",
    "debug": "debug",
    "test_generation": "test_generation",
    "explain_code": "explain_code",
}
