# Escopo — Nila como orquestradora (opt-in) + redução de tokens · 2026-06-27

**Objetivo do dono:** a Nila (modelo local) orquestrar o JARVIS — chamar tools, iterar, aprender
com erro, responder em texto — LOCALMENTE, matando rate-limit/contexto. **Opt-in** (nem todos têm
modelo próprio → fallback p/ a nuvem). Provedores de nuvem: **Groq (free) + OpenRouter (free/barato)**;
Gemini removido. Ver [[jarvis-modelo-diana-amigo]] e [[jarvis-model-routing-docgen]].

## Diagnóstico do gargalo (por que estoura)
O payload de tool-calling chega a ~9.800 tokens = **system prompt (~2k)** + **N schemas de tools
VERBOSOS (~300-450 tokens cada)** + memória semântica injetada + histórico. O 8b do Groq tem TPM=6.000
→ não cabe. A causa #1 é o **peso dos schemas de tools**, não o nº de tools.

---

## PARTE 1 — REDUÇÃO DE TOKENS (fazer PRIMEIRO: alivia a nuvem JÁ + é pré-requisito da Nila enxuta)
Padrões da pesquisa (MCP-Zero −98% tokens, RAG-MCP, planning/PESQUISA-ORQUESTRADOR-2026-06-26.md):

1. **Schemas COMPACTOS** (maior corte, baixo risco) — `to_openai_tools(compact=True)`:
   descrição da tool → 1ª frase (~120 chars); descrições dos ARGS → removidas (mantém nome+tipo+enum).
   ~400 → ~80 tokens/tool. Atrás de `AGENT_TOOLS_COMPACT`. Risco: menos guia p/ args → calibrar.
2. **Retrieval semântico** (JÁ feito — SkillMemory `layered`): manda só top-k (8) por significado.
   Combinado com #1: 8 tools × 80 ≈ 640 tokens (vs ~3-4k hoje).
3. **Tool de CONSULTA de tools** (on-demand, estilo MCP-Zero) — o modelo recebe só
   `nome — 1 linha` de cada tool candidata; quando decide, uma tool `detalhar_ferramenta(nome)`
   devolve o schema completo SÓ daquela. Tira o grosso do payload inicial. Risco: +1 round-trip.
4. **Enxugar descrições no registry** (fonte direta): `criar_relatorio` etc. têm descrições enormes —
   mover o "guia de blocos" p/ a memória semântica / situações, deixando a description curta.
5. **Memória/histórico fora do tool-calling** quando não precisar (já há compaction + os toggles).

**Ordem dentro da Parte 1:** #1 (compactos) + #2 (já on) → maior ganho imediato; depois #4 (enxugar) e
#3 (on-demand) se ainda apertar.

---

## PARTE 2 — NILA ORQUESTRADORA (opt-in, FÁSICA)
Toggle novo `NILA_ORCHESTRATOR_ENABLED` (OFF; só ativa se `MODELO_LOCAL_ENABLED` + sidecar presente —
o dono já tem `MODELO_LOCAL_ENABLED=true` + a pasta apontada). Sem a Nila → cai na nuvem (hoje).

Estado atual (`classifiers/modelo_local.py` + ambiente da Nila): sidecar `--stdio`
(`respond/perceive/train/state/ping/quit`), `request(op,arg)→dict`.

**CORREÇÃO (olhei o ambiente da Nila, 2026-06-27) — é MAIS simples do que eu escopei:**
- A Nila JÁ emite **ações JSON `{"acao":"<nome>", ...}`** (formato nativo dela; tools no corpus:
  pesquisar/comando/escrever/ler/calcular/sistema/disco/memoria/rede/listar_pasta/...). Ou seja: ela
  **já faz tool-calling**.
- A Nila JÁ **decodifica byte→texto sozinha** (a `respond` monta os bytes gerados em String). **Não
  preciso de decoder no JARVIS**; ela fica byte-nativa como o dono quer.
- Logo o que falta é só a **PONTE ação→tool do JARVIS** + (p/ cobertura total) **treino** nas tools do JARVIS.

### Fases (corrigidas)
- **Fase B1 — Ponte mínima (SEM mexer no Rust, SEM treino p/ começar):** JARVIS chama `respond <texto>`
  → parseia `{"acao":...}` na resposta → MAPEIA a `acao` da Nila p/ uma tool do JARVIS →
  `tool_registry.dispatch` → devolve o resultado via `respond <resultado>` → itera até a Nila dar texto
  final (sem ação). Cobre as tools que a Nila JÁ conhece (ver tabela). Resto → fallback nuvem. Atrás de
  `NILA_ORCHESTRATOR_ENABLED` (OFF, opt-in; só com `MODELO_LOCAL_ENABLED` + sidecar). **100% local = sem TPM/TPD.**
- **Fase B2 — Cobertura total:** treinar a Nila com as INSTRUÇÕES das tools do JARVIS (mesmo método do
  corpus dela → `perception.txt`) p/ emitir os nomes do JARVIS direto; opcional comando `orchestrate`
  no stdio p/ um loop mais limpo. CPU pesada só no treino (3-8 threads). A Nila consulta a tool de
  memória semântica p/ o que precisar (ideia do dono), em vez de inflar contexto.
  - **Lado JARVIS (FEITO 2026-06-27):** gerador de corpus `tools/nila_corpus.py` (determinístico, sem
    rede/LLM) — lê o `tool_registry` + `situations.CURATED` e emite o texto de treino com os nomes/params
    EXATOS do JARVIS no formato byte dela (`{"acao":"x", "p":"..."}`), incl. exemplos pedido→ação e
    dourados com argumento real. Saída em `data/nila/corpus_tools_jarvis.txt` (gitignored). NÃO documenta
    a arquitetura interna dela — só o formato público de ação.
  - **Segurança (FEITO):** allow-list `NILA_ALLOWED_TOOLS` (config + prefs `agent.nila_allowed_tools`).
    Com a Nila emitindo nomes reais, a ponte só AUTO-executa local as tools read-mostly (default:
    pesquisa_web, comando_terminal, clima, aprender_sobre, memoria_buscar, analisar_tela); sensíveis
    (enviar_mensagem, abrir_app, criar_relatorio…) CAEM NA NUVEM. `"*"` libera todas (confiança total).
  - **`orchestrate` no stdio (Rust): PULADO de propósito** — a ponte B1 já faz o loop no lado JARVIS;
    mexer no Rust dela é IP-sensível e desnecessário. Reavaliar só se o loop stdio virar gargalo.

#### Runbook de treino (AÇÃO DO DONO — CPU, mexe no modelo dele, nunca commitar o .safetensors)
Baseado no COMPARTILHAR.md §8 dela (`perception.txt` → `--export`). `<NILA>` = `MODELO_LOCAL_DIR`.
```
# 1. gerar o corpus das tools do JARVIS
.venv\Scripts\python.exe tools\nila_corpus.py            # -> data\nila\corpus_tools_jarvis.txt

# 2. anexar à percepção dela (NÃO apagar o corpus de português que já está lá)
Get-Content data\nila\corpus_tools_jarvis.txt | Add-Content "<NILA>\perception.txt"

# 3. continuar o treino (SEM --fresh, p/ não perder o português) por uns minutos e salvar
cd <NILA>
cargo run --release -- --sparse --think-len 0 --minutes 20

# 4. exportar o cérebro novo (vira nila_mind.safetensors)
cargo run --release -- --export --sparse
```
Depois é só `agent.nila_orchestrator: true` (a allow-list já protege). Caveat honesto: 10M é fraco em
extrair argumento — espere a Nila acertar o NOME da ação (vocabulário) bem antes de acertar os params;
por isso a allow-list começa só no read-mostly e o resto fica na nuvem.

#### RESULTADO do 1º treino (2026-06-27, rodado a pedido)
Corpus anexado 5× ao perception (16.9→86.7KB), 15min/4threads, backups feitos. bits/byte EMA **6.35→1.27**
(carregou o cérebro certo). Export OK (10.056.460 params). Verificação via stdio: **vocabulário MIGROU**
pro formato de tool do JARVIS (cospe `{"acao"`, `- exemplo:`, `(parâmetros:`, nomes de tool) — mas ainda
**proto-texto embolado, não ação limpa** (esperado p/ 15min/10M). INSIGHT: ela aprendeu (train bbpb 1.27),
o gargalo é a `respond` decodificar em ALTA TEMPERATURA (afeto excitado no boot → surpresa~8.0). **Maior
lever agora: decode greedy/baixa-temp p/ ações** (param no stdio/geração dela — PROPOR antes de mexer).
Depois: treino mais longo. Brain treinado mantido; original em `.bak` (restore trivial). Orquestrador OFF +
fallback nuvem = seguro como experimental.

#### WARMUP testado → o fix é decode GREEDY (2026-06-27)
Descoberta: a respond FRIA embola (afeto excitado no boot = alta temperatura); AQUECER (perceive + `train N`)
ACALMA → respond vira **ação JSON limpa e válida** (`{"acao":"pesquisa_web","query":"X"}` etc.). Prova que o
treino pegou. MAS `train` custa ~5-10s/passo (CPU) → warmup síncrono trava a 1ª chamada por minutos = inviável.
Fiei a plumbing (`modelo_local.train` + `_nila_warmup` + `NILA_WARMUP_STEPS`) com **default 0 (OFF)**; fica p/
experimentação / warmup assíncrono. **FIX LIMPO = decode greedy/baixa-temp no sidecar** (Rust: temp≈0 no
respond) — sai limpo a frio, sem warmup; IP-sensível → PROPOR ao dono. Acurácia (arg real + tool certa) ainda
precisa de corpus mais diverso + treino mais longo. **Decisão pendente do dono:** (a) greedy decode no Rust
[eu proponho/faço com OK], (b) corpus diverso + treino longo, (c) deixar experimental por ora.

#### 2ª rodada: corpus DIVERSO + treino LONGO → NEGATIVO (mode collapse) (2026-06-27)
Dono escolheu (b). Reescrevi `nila_corpus.py` (paráfrases × args REAIS, embaralhado, 421 exemplos, sem "X"),
restaurei o cérebro original do .bak, treinei **30 min** (bits/byte 0.456), exportei. Verifiquei com args fora
do treino: **parse 5/6, mas tool-certa 0/6 e arg-real 0/6** — colapsou em `comando_terminal dir` p/ toda query.
**Treino mais longo OVERFITTOU → mode collapse** (emite o padrão dominante, não condiciona na pergunta curta).
CONCLUSÃO: corpus+treino sozinhos não resolvem query→ação num 10M com a `respond` atual; **mais treino é PIOR**.
O formato/vocabulário ela SABE; o gargalo é condicionar+decodificar → **precisa do trabalho no Rust** (greedy/
baixa-temp + ancorar na query) que foi adiado. Cérebro overfit fica inerte (orquestrador OFF); se ligado
mis-despacharia. **Recomendado restaurar o original** (.bak) até o fix de decode. Caminho seguro segue: nuvem.

#### 3ª rodada: fix no Rust (greedy + ancorar na query) → VEREDITO DEFINITIVO (2026-06-27)
Dono autorizou mexer no Rust dela. Editei (local, nunca commitado): `moe.rs::dream_continue` greedy quando
temp<=0; `mind.rs::respond_act` (estado fresco + observa só a query + greedy); `main.rs` stdio `act <query>`.
Recompilei OK. Testei `act` em 3 níveis de treino (8/12/30 min). **O greedy resolveu o DECODE (parse até 7/7,
sempre JSON válido), mas em TODOS os níveis a Nila NÃO condiciona na query — colapsa num padrão dominante,
tool-certa 0-1/7, arg-real 0/7.** CAUSA arquitetural original declarada: GRU byte-level 10M sem atenção/cópia não
faz pergunta→tool+arg. CONCLUSÃO PRECIPITADA (corrigida pelo dono).

#### CORREÇÃO DO DONO (2026-06-27) + retreino B2 continuado (2026-06-29)
**Dois erros meus:**
1. Loss-alvo: o TETO é ~1.2 bits/byte (não piso). Ir a 0.456 = overfit = colapso. O run de 12 min parando
   em 1.15 estava CORRETO. A conclusão "arquitetural" foi precipitada — nunca testei o alvo certo.
2. Decode: o `respond_act` com `temp=0` (greedy) shortcircuita a previsão dela. Ela tem que PREVER o bit
   (sampling em temp moderada), não retornar o argmax diretamente.
**Causa real do colapso (identificada 2026-06-29):** corpus = seed português (mesma frase ×110 = 16.9KB) +
tools (53KB). O DESTILAR reforçou o seed (padrão estável/repetitivo) → prior domina português, não ferramentas.
**Fix:** corpus-ONLY (sem seed português) na `perception.txt` + pesos pristinos.
**Estado das edições Rust (local, nunca commitar):**
- `moe.rs`: `MoeState` agora `#[derive(Clone)]`; greedy branch (temp≤0) ainda existe (backward-compat).
- `mind.rs`: `respond_act` — temp=0.5 (previsão, não argmax); primer inline ~1KB aquece o GRU do zero.
- `main.rs`: stdio `act` chama `respond_act` (inerte para produção).
**Resultado 4ª rodada (2026-06-29, corpus-only, 15 min, BPB 1.626):** output em DOMÍNIO DE FERRAMENTAS
(sem português!), fragmentos `{"acao":"..."}` mas muito ruidoso (BPB ainda alto, precisa chegar ~1.2).
**Continuação:** 2ª sessão de 15 min rodando para descer BPB de 1.626→~1.2. Decode: `perceive(primer)` +
`respond` (warm stream_state via perceive_text).

**APRENDIZADOS PERMANENTES:**
- `try_load` → `stream_state = moe.new_state()` (zeros). Estado sempre frio no startup.
- `respond` faz `perceive_text(arg)` antes de gerar → warm stream. `respond_act` não → precisa de primer.
- Para ativar ferramentas no `respond`: chamar `perceive(primer_tool_examples)` antes.
- Seed português extremamente repetitivo domina o prior; DESTILAR amplifica isso.
- BPB EMA é do corpus inteiro: BPB ótimo no seed puxa o EMA pra baixo mascarando BPB ruim no tools.
- Corpus-only resolve a dominância do seed; DESTILAR passa a reforçar ferramentas.
- Fine-tune de 30 passos em 7 exemplos → BPB 0.1999 (overfit imediato): usar poucos passos ou nenhum.
- **Afeto NÃO atualiza com `perceive`** — só com `train` (gradient) ou tick RL. No stdio modo, afeto
  arran a BPB~8.007 (Affect::new()) e PERMANECE lá. `perceive(corpus)` aquece `stream_state` (GRU
  hidden), mas não reduz `surpresa`. A temperatura do `respond` (via afeto) permanece ~8 → garbage.
- **`act` (respond_act) usa `stream_state.clone()` + temp=0.5** — não depende do afeto. Warmup via
  `perceive(corpus_completo)` (0.38s) aquece o stream_state → `act` clona o estado quente. Essa
  combinação produce JSON parseable (4/7) e tool name certa em ~2/7.
- **Limitação arquitetural real (confirmada):** GRU byte-level 10M CLASSIFICA a tool pelo tipo de pedido
  (pesquisa → pesquisa_web, pdf → criar_relatorio) mas NÃO COPIA o argumento da query → arg sempre errado.
  **Solução prática: o BRIDGE extrai o arg do pedido original do usuário**, usa só o NOME da ação da Nila.
- Warmup de `perceive(54KB corpus)` = 0.38s — viável como cold-start one-shot da sessão.
- **Fase C — Resposta:** já resolvida (a `respond` devolve texto via decode interno). Só MELHORA com
  treino no domínio (hoje proto-português p/ o nosso caso).

#### 5ª rodada: percive-corpus + act (2ª sessão treino + teste novo decode) (2026-06-29)
2ª sessão treino corpus-only (15 min) finalizada: BPB final ~1.100 (oscila 0.846-1.432). Export limpo feito.
Diagnóstico crucial: afeto NUNCA cai com `perceive` — Affect::new() = BPB~8 permanece. Tanto `perceive(5KB)`
quanto `perceive(54KB)` resultam em exatamente o mesmo `surpresa=5.550 bits/byte~8.007`. O GRU stream_state
SI aquece (forward pass), mas afeto não.
Mudança: `respond_act` voltou a usar `stream_state.clone()` (estado quente, não new_state). Fluxo:
`perceive(corpus_completo)` (0.38s) → aquece stream_state → `act(query)` usa clone do estado quente + temp=0.5.
**RESULTADO HONESTO: parse JSON 4/7 (57%), mas tool_certa 0/7** — os 4 parses são `abrir_site` e `criar_relatorio`
para qualquer query (bias do corpus, não classificação real). O modelo NÃO classifica o tool certo neste nível.
Sessão 3 de treino (15 min a mais): BPB caiu para 0.486 (overfit de novo) → parada preventiva. mind_state.bin
ficou com estado overfit; safetensors (00:30) permanece na versão sessão 2 (melhor disponível, BPB ~1.1).
Bridge atualizado: `_nila_warmup` agora usa `perceive(corpus)` (0.38s, não train); `act` em vez de `respond`
na 1ª chamada; `_nila_extract_args` extrai args do pedido original. Mas com tool_certa=0, o bridge cai na
nuvem para tudo na prática — o guard `acao não mapeada → nuvem` cobre.
**CONCLUSÃO:** O modelo de 10M precisa de teacher distillation (27B/AirLLM) para accuracy real. As sessões
corpus-only estabilizaram o domínio (sem português, JSON parseable) mas não resolvem a classificação. Deixar
OFF (orquestrador) é seguro. Retomar com 27B quando o dono tiver tempo.

### Ponte ação→tool (tabela inicial)
`pesquisar`→pesquisa_web · `comando`→comando_terminal · `calcular`→(cálculo) · `sistema`/`disco`/
`memoria`/`rede`→controle_sistema/infos · `escrever`/`ler`/`listar_pasta`/`procurar_arquivo`→tools de
arquivo. O que a Nila não conhece (spotify/pdf/whatsapp/relatório/...) fica na nuvem até a Fase B2 (treino).
Risco: a `respond` hoje é curta (140 bytes) + undertrained p/ o nosso domínio → a B1 cobre o overlap, o
resto cai na nuvem; a B2 (treino) é o que dá cobertura real.

---

## ORDEM RECOMENDADA
1. **Parte 1 #1 (schemas compactos) — FEITO (2026-06-27):** `AGENT_TOOLS_COMPACT` (on nas prefs do dono)
   → tools −27% (40.865→29.530 chars). #2 (retrieval semântico) já on. Alívio imediato.
2. **Fase B1 (ponte Nila, SEM Rust) — FEITO (2026-06-27):** `_orquestrar_nila` em `main.py` (bridge
   `respond → parse {"acao"} → mapeia/dispatch → devolve via respond → itera`, atrás de
   `NILA_ORCHESTRATOR_ENABLED` (OFF), fiado ANTES do `_pensar_e_agir`). `_NILA_ACAO_MAP`: `pesquisar→
   pesquisa_web`, `comando→comando_terminal`; + **forward-compat** (se a Nila emitir um nome de tool do
   JARVIS direto, despacha — pós-B2). Ação não coberta / proto-texto → nuvem. Verificado (compile +
   parse/map). LIGAR: prefs `agent.nila_orchestrator: true` (+ `MODELO_LOCAL_ENABLED` já on).
3. **Fase B2 (treino + cobertura total) — LADO JARVIS FEITO (2026-06-27):** gerador `tools/nila_corpus.py`
   (corpus das tools do JARVIS no formato dela) + allow-list `NILA_ALLOWED_TOOLS` (sensíveis caem na
   nuvem) + runbook de treino acima. Falta só a AÇÃO DO DONO: rodar o treino (CPU) e exportar o cérebro.
   `orchestrate` no stdio: pulado (a ponte já cobre). O salto que mata os limites de vez.
4. **Parte 1 #3/#4** (tool on-demand + enxugar descrições verbosas no registry) conforme apertar.

## RISCOS / UNKNOWNS
- Confiabilidade do formato de tool-call da Nila → exige treino no nosso domínio/tools (a porta existe).
- Extensão do sidecar Rust (orchestrate/embed) — eu implemento.
- Schemas compactos demais → LLM erra args; calibrar com `tools/eval_tools.py`.
- Manter SEMPRE o fallback p/ a nuvem (opt-in; nem todos têm a Nila).
- CPU: treino/inferência da Nila em 3-8 threads (dono já setou `MODELO_LOCAL_THREADS=3`).

**Invariantes:** Nila nunca no GitHub · IP confidencial (não propagar arquitetura) · toggles OFF ·
edição direta sem commit · provedores: Groq+OpenRouter (sem Gemini).
