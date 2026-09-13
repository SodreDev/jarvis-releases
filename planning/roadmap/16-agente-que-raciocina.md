# 16 — Agente que RACIOCINA (deixar de ser automação rígida)

> Baseado em pesquisa de **projetos REAIS** (2026), não hipóteses. Objetivo: o JARVIS
> raciocinar e executar como um agente de verdade (estilo Open Interpreter / OpenHands /
> Goose / Cline / Hermes / OpenClaw / Claude Cowork), mantendo a persona — sem virar
> lento, verboso ou caro. Tudo cirúrgico, atrás de toggles, `_pensar_e_agir` como motor.

## Projetos estudados (o que cada um ensina)
- **Open Interpreter** — plano no prompt + **histórico guarda a ação executada e a saída**
  (por isso "lembra do arquivo que criou"); streama o pensar/fazer.
- **OpenHands** — loop event-sourced com **trace de raciocínio**; condensers resumem;
  erro → **re-tenta com alternativa mais segura** (não repete igual).
- **Aider** — **separar RACIOCÍNIO de FORMATAÇÃO** (architect/editor) sobe acerto +3-7pp;
  RepoMap = só o contexto relevante.
- **smolagents** — loop minúsculo explícito; traceback volta pra memória → reescreve.
- **Goose** — **Planning Mode** (planner dedicado antes de executar); subagentes isolados
  devolvem só resumo; "Show reasoning".
- **Cline/Roo** — **Plan/Act** (plano read-only → executa); **Focus Chain** (todo re-injetado
  sobrevive à compactação); checkpoints.
- **Hermes (Nous)** — `<scratch_pad>` Goal/Actions/Observation/Reflection; function-calling
  estrito; persona estável no system; skills que se auto-melhoram.
- **OpenClaw** — local-first, **age por você** (shell/browser/arquivos); índice de skills
  enxuto sob demanda; **act-vs-ask** (age por padrão, pergunta só com julgamento humano);
  memória em arquivos legíveis (SOUL/MEMORY).
- **Omi** — memória em camadas + **grafo de entidades** (segundo cérebro).
- **Claude Cowork** — modo agêntico (gather→act→**verify**→repeat), compactação automática.
- **AutoGPT (cautela)** — sem STOP/dedup vira loop infinito; manter caps.

## As 4 causas-raiz do "jeitão de automação" (dos seus logs)
1. **Não raciocina / fala templated** → o `_TOOL_SYSTEM_PROMPT` **proibia** raciocínio e
   forçava "1 frase Feito, Senhor". **Causa-raiz #1.**
2. **Não lembra o que criou** ("o PDF") → sem ponteiro de artefato + memória/histórico OFF.
3. **Pede dado que já tem** ("qual projeto" p/ mover o PDF) → sem defaults sensatos + tool
   mal desenhada + sem correferência.
4. **Não decompõe tarefa composta** ("pesquisa + PDF + PowerPoint") → ReAct puro sem plano.

## ✅ Já implementado (2026-06-22, build 5)
- **Prompt "AJA COMO AGENTE QUE RACIOCINA"**: raciocínio interno permitido; **AJA por
  padrão** (não sugira/peça permissão); **infira defaults** e sinalize; **execute tarefa
  composta em sequência**; resolva referências por contexto/memória; **fala lidera com o
  resultado** (varia, não repete "Feito"). + soft no MODO VOZ.
- **Memória de ARTEFATO** (`self._last_artifact`, em sessão, independe de MEMORY_ENABLED):
  captura o último arquivo criado (path/tipo) no `_on_tool_dispatched` e **injeta sempre**
  no contexto → "esse PDF / aquele / de novo / move ele" resolve **sem perguntar**.
- Bugs do log: imagem `Nano Banana` (era 404), atalho de "mover" não sequestra mais movimentação
  geral, provider do cérebro respeita "Provider — Chat", 413 re-tenta primário, fala mais curta.

## Plano (priorizado por IMPACTO / RISCO — toggles OFF até validar)
1. **(feito/parcial) Contexto que faz lembrar** — `last_artifact` (✓) + recomendar
   `AGENT_INCLUDE_HISTORY=ON` (turno anterior p/ "esse aí/manda pra ele") + `MEMORY_ENABLED=ON`.
   Risco ~0.
2. **Raciocínio VISÍVEL (scratchpad estruturado)** — `AGENT_REASONING` (OFF): antes da 1ª
   tool, o LLM emite **Goal→Plano(1-3 passos)→Reflexão CURTOS** (template estruturado estilo
   Hermes, **não** CoT livre — melhora modelo barato sem quebrar tool-calling). **Canal
   separado**: o plano vai pra UI ("pensando: …"); a **fala TTS continua telegráfica**.
   Resolve "não raciocina/templated". Risco médio → testar com modelo barato.
3. **Defaults sensatos + tool de arquivo** — destino vira parâmetro **opcional nullable com
   default** (Documentos/pasta do arquivo), inferido do `last_artifact`; regra global "default
   + sinalize, não pergunte salvo ambiguidade com custo". Adicionar uma tool real de
   **mover/gerenciar arquivo** (hoje só há file-op de IDE). Resolve "pede dado".
4. **Reflexão entre passos** — estender a auto-correção (hoje só em ERRO) para uma reflexão
   curta de "isto resolveu? falta algo?" em tarefa composta, com orçamento 1-2 (Reflexion).
5. **Tier SUPERVISE / `lead.py`** (roadmap/15 Fase 4) — roteador de COMPLEXIDADE + decompor
   tarefa composta em plano JSON `[{passo, domínio, deps}]`, persistir na memória, mostrar
   na UI (estilo TodoWrite/Focus Chain), executar cada passo via `_pensar_e_agir` **já
   escopado por domínio** (Fase 3 pronta), digest de volta. Paralelo só na nuvem; 1 nível;
   caps. Resolve "não decompõe". Maior esforço/custo → por último.

## Persona coerente (anti-drift, ID-RAG)
Persona/estilo no system (read-only) re-injetada a cada request + **2-3 few-shots de TOM**
(1 exemplo é ruído). Persona = regras de comunicação concretas ("lidere com o resultado",
"não narre a deliberação", "aja, não sugira"), não adjetivos.

## Guarda-corpos (lições AutoGPT/Cognition)
Manter `MAX_STEPS`/timeout/dedup; raciocínio **estruturado e curto** (não monólogo);
multi-agente **só** no tier SUPERVISE (custo 4-15x); STOP/"good enough" explícito;
verify antes de declarar sucesso (nunca "Pronto" falso).

## Validação (regra do projeto)
`py_compile` a cada passo + `tools/eval_tools.py` estendido: casos {referência 'o PDF' → usa
`last_artifact`, NÃO pergunta} e {tarefa composta → decompõe}. Medir tom (não-templated) com
paráfrases. Tudo OFF por padrão; comportamento atual = fallback universal.

## Fontes
Open Interpreter docs; OpenHands (arXiv 2511.03690); Aider architect/editor; HF smolagents;
Goose docs; Cline plan/act; Nous Hermes (github.com/nousresearch); OpenClaw; Omi (Based
Hardware); Claude Cowork (Anthropic); LangGraph planning-agents; When-to-Reason; Pre-Act;
arXiv 2509.18076 (scratchpad estruturado). URLs completas nos outputs da pesquisa.
