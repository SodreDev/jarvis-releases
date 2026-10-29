# Handoff — provedores de modelo, presets e roteamento por capacidade (ADR-0056)

**Autor:** opus-provedores · **Data:** 2026-10-29 · **Branch:** master (push para `origin/reescrita`).

Pedido do dono: mais autonomia na escolha de modelo — listar **todos** os modelos de cada provedor
(endpoint oficial, cache e lista estática de reserva), escolher entre Anthropic/Claude, OpenAI,
Codex, OpenCode, OpenRouter e roteadores, Groq; salvar modelo + esforço como **preset** por papel
(cérebro, Jev, visão, resumo), trocar pela janela e pela voz, e **rotear** por capacidade (imagem
vai a quem vê).

## Commits

| fatia | commit | o quê |
|---|---|---|
| A | `d59435b` | ADR-0056 (desenho, fontes oficiais lidas em 2026-10-29) |
| B | `33f67bf` | núcleo `jarvis.provedores`: interface, registro, catálogo com cache; eco e CLI do Claude migrados; `--effort` do preset |
| C | `2952dc8` | OpenAI, OpenRouter, Groq, compatíveis (local e nuvem), Codex, OpenCode 1.x; lista da Anthropic com `ANTHROPIC_API_KEY` |
| D1 | `1b5fb61` | presets (`presets.toml`), `modelo.preset` pela voz, atalho do código e PDP |
| E | `8a31b9e` | `MotorDosPresets`: o cérebro segue o preset ativo; imagem → preset de visão; Jev pelo preset |
| D2 | o commit seguinte a `8a31b9e` | a janela: `PonteDeModelos` + `PainelDeModelos.qml` no painel «resposta»; a janela e o cérebro com a mesma `FonteDePresets` |

## Mapa

- `licenses/provedores-de-modelo.toml` — um `[[motor]]` por provedor (`conversa-*`), no formato e com
  o portão de `licenses/motores.toml` (`exigir_motor` com outro `arquivo`), e `[[capacidade]]` por
  padrão de id, cada uma com fonte e data. O compatível de nuvem nasce **sem termos** (só chama com
  `nuvem_sem_termos`).
- `src/jarvis/provedores/`: `interface.py` (Capacidades `None` = não informado; esforços
  `none…max`; `esforco_do_modo`: pensar sobe para ≥ high), `registro.py`, `catalogo.py` (fresca 24 h
  → ao vivo → guardada → registro; `$XDG_CACHE_HOME/jarvis/modelos/<id>.json`), `nucleo.py`
  (`Provedores`: listar, capacidades, `motor` pelo portão; `ligados_da_configuracao`: `s2="claude"`
  conta como ligado), `stream.py` (SSE num fio, cancelamento fecha o socket), `compativel.py`
  (Chat Completions; `FiltroDePensamento` tira `<think>`; OpenRouter com `data_collection: deny`),
  `processo.py` (CLIs: pasta vazia, ambiente sem as chaves do Jarvis, morto no cancelamento),
  `codex.py`, `opencode.py`, `existentes.py` (eco, CLI do Claude), `presets.py` (+ `presets.toml`),
  `roteador.py` (`MotorDosPresets`).
- `catalogo/modelo.preset.yaml` (+ stub gerado), `src/jarvis/politica/preset.py` (o portão: turno do
  dono; com conteúdo de fora, o sim), atalho `Regra.TROCAR_PRESET` em `politica/atalho.py`,
  `executor/ferramentas.py` (`TrocaDePreset`, `presets`), `voz/app.py` (`fonte_de_presets`,
  `_troca_de_preset` — só com a pasta do dono —, `motor_de_conversa` devolve o roteador,
  `_modelo_do_jev`).
- A janela: `src/jarvis/gui/modelos.py` (`PonteDeModelos`, exposta como `ponte.modelos`: provedores,
  presets, ativos, a lista do provedor aberto; listar e perguntar a prontidão das CLIs em thread, com
  sinal enfileirado para a thread da janela) e `qml/JarvisUI/PainelDeModelos.qml` no painel
  «resposta» da `VistaConfiguracao.qml` (substituiu os botões eco/claude; `ponte.geradores` ficou
  sem uso no QML). Ligar nuvem vale na sessão; «salvar configuração» grava, como no painel de voz.
  A ponte passa a fonte de presets dela à sessão (`SessaoDeVoz.presets` → `Aplicativo.presets`): o
  que a janela grava é o que o cérebro lê, inclusive com `--config`.
- Configuração nova: `base_compativel_local`, `base_compativel_nuvem`. Chaves novas no chaveiro da
  janela: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `JARVIS_COMPATIVEL_API_KEY`; `sk-` entrou na
  recusa por forma de chave.

## Decisões e armadilhas

1. **Modelo não precisa estar numa lista para chamar** (diferente da voz): a lista de um LLM muda
   toda semana; o portão é por provedor (termos). O id só precisa ter forma (`FORMA_DO_ID`, que aceita
   `[]` por causa de `sonnet[1m]`). Quem diz se existe é o provedor.
2. **Nunca troca de provedor sozinho.** Preset que não roda termina o turno com o motivo; sem rota
   que vê, a imagem fica de fora.
3. **O preset da configuração** (`DA_CONFIGURACAO`) só existe em memória: `para_toml` não o grava, e
   desfazer de volta para ele grava o ativo vazio.
4. **OpenCode 2.x** (saiu em 2026-10-29) é recusado pela versão: mudou permissões, credenciais e a
   sintaxe do variante, e a saída do `run --format json` não é documentada nem na 1.x — o leitor
   junta partes `text` e para no `step_finish`/`stop` (há relato de a CLI ficar parada depois).
5. **Codex:** `codex debug models` é comando de depuração (formato não documentado; leitor
   defensivo). Os termos de consumo da OpenAI (trecho de busca) proíbem extrair saída de forma
   automatizada: está no aviso; a decisão é do dono.
6. **Teto do prompt** (`tests/unit/s2/test_regras_e_catalogo.py::test_o_prompt_do_turno_cabe_no_teto`):
   já estava em 16 140 > 16 000 **antes** destas fatias (veio de commits da outra CLI, ex.
   `browser.fechar_aba`); a `modelo.preset` não entra no catálogo daquele teste e, na janela, soma
   ~100 caracteres por turno. Não mexi no teto.
7. **Proteções que a revisão da janela pediu** (agora no backend, valem para a voz também): o arquivo
   do dono que existe e não serve **não é sobrescrito** (`FonteDePresets.gravar` recusa e diz
   «conserte-o ou apague-o»); «configuração» é nome reservado; o preset em memória não conta no
   teto de 40; a recusa de chave não repete o valor nem manda «apagar do arquivo» antes de gravar.
8. **Várias CLIs no mesmo repositório:** o D1 foi comitado com índice temporário e
   `commit-tree` + `update-ref` com o HEAD antigo (o `app.py` tinha trechos da E junto).

## Não provado em máquina real

Nenhuma chamada a provedor de verdade (listar ou conversar), nenhuma CLI real (`claude`, `codex`,
`opencode`) rodou, a CLI do Claude com `--effort xhigh`/`max`, o pedido com imagem indo ao modelo de
visão real, e a janela nova com o dono clicando. Tudo foi provado com provedores falsos, servidor
HTTP local (`CI=1`) e executáveis falsos.

## Próximos passos sugeridos

- Consumidor do papel `resumo` (ex.: resposta grande montada na tela, ADR-0055): `MotorDosPresets.
  motor_do_papel("resumo")` já entrega o motor.
- Ligar provedor de nuvem sem reabrir a conversa (hoje o roteador lê `nuvem_ligada` ao abrir).
- Ler a 2.x do OpenCode quando a saída do `run` for documentada.
