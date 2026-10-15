# F0-08 — C1: memórias do Orchestrator no esquema da §6.2

**Gerado por** `tools/exportar_orchestrator.py --relatorio` (não editar à mão). **Fonte:** mcp-orchestrator-list_memories-1792085016958.txt.

## `n` de C1

| tabela | n |
|---|---:|
| `episode` | 128 |
| `entity` | 331 |
| `assertion` | 128 |
| `memory_unit` | 128 |
| `entity_mention` | 943 |
| `entity_edge` (todas) | 2990 |
| `entity_edge` com `status='active'` | 676 |

- **2.6 entidades por episódio** e **23.4 arestas por episódio** (todas; 5.3 ativas por episódio).
- Aresta nasce `proposed` e vira `active` só com duas evidências independentes (§6.7): é por isso que os dois números são diferentes.

## Redação de segredo (aceite (a))

Trechos redigidos: **2**.

| padrão | ocorrências |
|---|---:|
| `email` | 2 |

Classe de PII dos episódios: `metadata`: 2, `none`: 31, `path_only`: 83, `sensitive`: 12.

## Para que serve este número

O cartão F0-05 dimensiona o grafo sintético pelo corpus real. A medição publicada em `f0-05-grafo.md` usou **122 episódios** como base, com a razão **[SUPOSIÇÃO]** de 3 entidades e 8 arestas por episódio; a tabela acima substitui a suposição pela contagem medida, e a comparação está nas notas do executor (`docs/notas-executor-F0.md`, seção F0-08).

## O que **não** está aqui

- o conteúdo exportado: fica em `corpus/exportado/`, fora do repositório, porque é texto do dono e é reconstituível;
- extração de entidade por LLM: a extração do C1 é **determinística** (autor, projeto, tema, caminho de arquivo, commit), como manda a §6.7;
- qualidade: C1 serve para dimensionar e calibrar, não para medir recall — isso é C2 (`corpus/consultas/`), em F3.
