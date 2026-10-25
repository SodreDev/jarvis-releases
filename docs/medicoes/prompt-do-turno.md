# O prompt de sistema de cada turno — antes e depois da ADR-0047

Data: 2026-10-25. Reproduzível com (sem rede, sem o desktop do dono):

```bash
git show 016c0a6:src/jarvis/s2/persona.md > /tmp/persona-v14.md   # a persona de antes
uv run --frozen python -m tools.medir_prompt --antes /tmp/persona-v14.md
```

O que vai ao motor (`claude -p`) em **todo** turno, antes da conversa: a persona, as regras do dono
(novas) e o catálogo de ferramentas. Medido com um executor de todas as famílias ligadas (61
ferramentas visíveis no modo `padrao`: apps, janelas, navegador, web, arquivos, memória, tarefas,
lembretes, sistema, vocabulário, encerrar). Tokens pelo tokenizador do embedding da memória
(multilingual-e5-small, SentencePiece do XLM-R) — uma aproximação: o tokenizador do Claude não é
público; a ordem de grandeza e a proporção entre antes e depois é o que importa aqui.

### antes (persona v14, sem regras, catálogo com o esquema JSON)

| bloco | caracteres | tokens (e5) |
|---|---:|---:|
| persona | 7915 | 2120 |
| catálogo (61 ferramentas) | 22635 | 7969 |
| total do prompt de sistema | 30550 | 10089 |

### agora (persona v15, regras padrão, catálogo gerado)

| bloco | caracteres | tokens (e5) |
|---|---:|---:|
| persona | 4580 | 1206 |
| regras do dono | 714 | 192 |
| catálogo (61 ferramentas) | 9234 | 2862 |
| total do prompt de sistema | 14530 | 4260 |

## O que mudou

- **Catálogo** (−59% em caracteres, −64% em tokens): cada ferramenta numa linha — o nome com os
  argumentos (`url*, segundo_plano:bool, acao*=tocar|pausar`), quando usar (o `quando` do
  manifesto) e até três pedidos naturais do dono (os `exemplos` do manifesto) — no lugar da
  descrição e do esquema JSON inteiro de cada argumento. Gerado do registro (`catalogo/*.yaml`), em
  ordem estável: o começo igual em todo turno é o que o cache de prompt reaproveita.
- **Persona v15** (−42%): seções (identidade e tom, princípios de ação, o que fazer sem perguntar,
  quando perguntar, voz e tela, memória e nomes, segurança); o procedimento de cada ferramenta
  (inspecionar e agir pelo ref, a tela da aba, o @ do canal, o foco que vai sozinho) foi para o
  `quando` do manifesto dela — fica uma vez, no catálogo.
- **Regras do dono** (+714 caracteres): o bloco curto e editável (`~/.config/jarvis/regras.toml`,
  padrão em `src/jarvis/s2/regras.toml`).

O total caiu de ~30,5 mil para ~14,5 mil caracteres por turno. O teste
`tests/unit/s2/test_regras_e_catalogo.py::test_o_prompt_do_turno_cabe_no_teto` segura em 16 mil.

## Limite honesto

O efeito no tempo até o primeiro token **não foi medido** com o `claude -p` de verdade (custaria
chamadas na conta do dono, e a CLI decide sozinha o cache): menos tokens de entrada só podem
diminuir o pré-processamento, mas quanto isso pesa contra a latência de rede e da própria CLI (~3 s
no p50, ADR-0045) é o que a trilha do dono vai mostrar (`ms_primeiro_token`).
