# Como contribuir

A especificação manda. Em conflito entre código e [`docs/SPEC-v0.md`](docs/SPEC-v0.md), o código
está errado até a SPEC ser emendada por ADR.

## Proibições que fazem a revisão recusar o patch

Do contrato de capacidade (SPEC §4) e dos princípios P1, P2, P6 e P12:

1. **Sem tool "canivete suíço".** Nada de `run_command`, `do_anything`, `eval`, shell irrestrito
   ou qualquer capacidade cujo poder dependa do texto que o modelo escreve. Abrir aplicativo é
   capacidade tipada com `app_id` de registro versionado — nunca `argv` livre.
2. **Nenhuma frase dispara ação** (P2). Não existe mapa de palavra, regex ou intent fixo ligado a
   efeito. Palavra só chega a efeito pelo catálogo tipado mais o PDP.
3. **O código autoriza, o modelo propõe** (P1). Decisão de política é determinística, fora do LLM,
   e nunca lê campo de política vindo de servidor remoto ou de conteúdo.
4. **Tudo que vem de fora é dado** (P6). Transcrição, tela, web, retorno de tool e servidor MCP são
   `untrusted`/`third_party`: não ampliam `allowed_tools`, não viram política nem memória durável.
5. **`trust` é atribuído por quem recebe do mundo**, nunca aceito do emissor.
6. **Sem shell no caminho de produção.** O linter barra `subprocess` com `shell=True`, `os.system`
   e `eval`/`exec` (regras `S` do ruff). Em teste, use processo com `argv` explícito.
7. **Nível de acesso e elevação só mudam pela UI, com o dono presente** (P12). Nenhuma capacidade
   os altera; patch que adicione uma é recusado.
8. **Nenhum número inventado.** Medição entra no repositório com hardware, `n`, 3 execuções,
   mediana e p95. Estimativa vai marcada como **[SUPOSIÇÃO]** e com o teste que a confirma.
9. **Licença é requisito** (ADR-0011): dependência ou modelo com cláusula não comercial ou
   "research only" não entra. A porta de licença roda no CI.
10. **Portável desde o primeiro commit** (P11): o que não roda em Linux **e** Windows não fecha
    tarefa. Caminho com `pathlib`, nada de dependência de X11 ou de systemd no caminho crítico.

## Antes de abrir o patch

```bash
uv run --frozen python tools/verificar.py
```

Precisa passar nos dois sistemas. Commit pequeno, um assunto por commit, mensagem em português
com o cartão no assunto (ex.: `F0-02: ...`) e o aceite do cartão colado no corpo.
