# F2-02 — piso do `claude -p` provisório: o que cada flag tira do spawn

**Gerado por** `tools/harness_claude_cli.py` (não editar à mão). **Data:** 2026-10-17. **Commit:** `6716263`.

> **Com rede e com a conta do dono**: número desta máquina, desta rede, desta hora. As variantes rodaram intercaladas, então a rede pesa igual nas três.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM; Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- `MotorClaudeCli.gerar` (o do produto), stream-json, modelo `haiku`, esforço `low`, pasta vazia, prompt de sistema do produto; tempo contado de antes do `Popen`
- 4 perguntas curtas × rodadas, intercaladas por variante

## Resultado

| variante | o que muda | n | 1º token p50 | 1º token p95 | 1ª fronteira p50 | 1ª fronteira p95 | fim p50 |
|---|---|---:|---:|---:|---:|---:|---:|
| `antes` | o argv de antes desta medição | 24 | 2145 ms | 4140 ms | 2160 ms | 4177 ms | 2335 ms |
| `safe-mode` | + --safe-mode (sem CLAUDE.md, skills, plugins, hooks, MCP) | 24 | 1691 ms | 2342 ms | 1753 ms | 2342 ms | 1934 ms |
| `safe-mode+sem-trafego` | + --safe-mode e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 | 24 | 1575 ms | 2739 ms | 1671 ms | 2762 ms | 1851 ms |

## O que já estava no `argv` antes (e por isso não é variante)

`--tools ""`, `--strict-mcp-config` (nenhum servidor MCP), `--no-session-persistence`, `--disable-slash-commands`, `--system-prompt` do produto (curto, no lugar do padrão), `--effort low`. `--bare` ficou fora: ele só autentica por `ANTHROPIC_API_KEY` e não lê o login OAuth do dono.
