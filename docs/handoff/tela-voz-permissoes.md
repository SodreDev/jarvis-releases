# Handoff — cortar é cancelar, falar curto, montar HTML na tela, permissões com menos atrito

Pedido do dono de 2026-10-29, em quatro partes e um item extra, um commit (ou dois) por parte, todos
com push. O que mudou, onde está, como testar e o que **não** foi provado. A CLI que fez:
`opus-tela-voz-permissoes`.

| parte | commit | ADR |
|---|---|---|
| 1. o bug do TTS que voltava a tocar | `3f36cb3` | 0040 emenda (2), 0025 emenda |
| 2. falar curto do jeito certo | `97c7b63` | 0031 e 0046 emendas |
| 3. montar e mostrar HTML na tela | `4f3d145` | 0055 (nova), 0019 emenda |
| 4. permissões com menos atrito | `f8cc350` | 0057 (nova), 0048 emenda |
| extra: várias delegações, um sim | `1543a6e` | 0054 emenda |

## 1. Cortar é cancelar (ADR-0040 emenda (2), ADR-0025 emenda)

**Causas medidas** (a trilha do dono de 29/10, só códigos, e reproduzidas em teste antes do
conserto):

1. Na escuta contínua sem o detector de endereçamento (a configuração dele naquela hora), a vigia não
   tinha regra para cortar: toda fala por cima dava `pausar suspeita` → `retomar prazo_da_pausa`
   (4 de 4 na trilha, nenhum corte). O prazo marcava o resto da fala como «contida» — não cortava de
   novo — e o pedido sumia, com a resposta velha seguindo até o fim.
2. O aviso cortado (a resposta de uma tarefa) voltava para a fila: tocava de novo inteiro no piso
   livre (13,5 s de áudio repetido no teste) ou ia na frente da resposta ao pedido seguinte.
3. O laço esperava até 2 s pelo cérebro do turno cortado sem ler o microfone, e depois o turno novo
   podia rodar junto com o velho.

**Onde está:** `voz/interrupcao.py` (`Motivo.FALA_DO_DONO`, `CONCORDANCIAS`,
`MAXIMO_DA_PAUSA_COM_LEITURA_MS`, `_descartar(contida=False)` no prazo, eco por sequência),
`agentd/fila_de_avisos.py` (`cortado_pelo_dono`), `voz/app.py` (`ESPERA_DO_CEREBRO_CORTADO_S`,
`_cerebro_em_voo`, `depois_do_fim`, `_parar_o_turno_cortado`). Testes:
`tests/unit/voz/test_corte_de_verdade.py` (laço inteiro, WAV sintético) e
`test_interromper_por_voz.py`.

## 2. Falar curto (ADR-0031 emenda, ADR-0046 emenda)

Sai o corte mecânico de quatro frases. A persona v16 encurta por natureza; o código só segura o
monólogo (`PALAVRAS_NA_VOZ` = 120, ~45 s) e, passado dele, para numa frase inteira e **pergunta**
«Quer que eu monte o resto na tela?». Pedido de detalhe, sem teto. `s2/orcamento_da_fala.py`,
`s2/persona.md`, `s2/regras.toml`. Testes: `tests/unit/s2/test_falar_menos.py`.

## 3. A tela do Jarvis (ADR-0055, ADR-0019 emenda)

`tela.mostrar` / `tela.ler` / `tela.fechar` (livres, só com a janela). O HTML vai pela allowlist de
`tela/sanitizar.py` (o subconjunto do texto rico do Qt, sem `a` e `img`; CSS refeito; nada de `url()`,
script, formulário), é limpo de novo na fronteira da janela (`componentes.validar_dados`) e conferido
por uma negação independente (`RECURSO`), e é desenhado pela `VistaConteudo.qml` — a única com texto
rico. Tema do Jarvis antes da folha do modelo; grade de tabela pelo atributo `border` (o Qt não
desenha a borda de célula por CSS — medido); o modo assistente vira pesquisa enquanto o conteúdo está
aberto. O guia de design vai ao prompt **só** no turno da tela (398 tokens; as 3 linhas do catálogo
custam 141 em todo turno com a janela — `docs/medicoes/prompt-do-turno.md`).

**Medido:** o texto rico do QML busca `<img src>` e `url()` na rede (3 requisições;
`tools/sonda_rede_da_tela.py`); limpo, 0. **Armadilha que custou tempo:** bloquear a rede no próprio
Qt pelo Python (fábrica de gerente de rede, proxy do aplicativo) derrubou o processo em ~50% das
rodadas no PySide6 6.9.3 — a carga de imagem remota do QML com outras janelas abertas é instável. A
garantia é nada remoto chegar à tela. Testes: `tests/unit/tela/`,
`tests/unit/gui/test_conteudo_na_tela.py`.

## 4. Permissões com menos atrito (ADR-0057, ADR-0048 emenda)

- **O «sim» natural** (`s2/portao.py`, `resposta_literal`, a mesma na voz e no cérebro): «sim, pode
  seguir», «vai em frente», «melhor não»; o ambíguo nunca autoriza; na voz o sim cobra os sinais
  fortes (ADR-0043). A pergunta por ação de uma tarefa é dita e respondida por voz.
- **O escopo do pedido** (`politica/escopo.py`): a tabela do contido (roda sem pergunta) e do que
  nunca é; o portão a usa; `browser.fechar_aba` (nova, moderada) fecha sem pergunta a aba que o pedido
  abriu ou a do site citado, e pergunta nas outras. A extensão ganhou `tabs.close` (0.1.1:
  **o dono precisa recarregá-la**).

Testes: `tests/unit/politica/test_escopo.py`, `tests/unit/s2/test_resposta_natural.py`,
`tests/unit/voz/test_confirmacao_por_voz.py`, `tests/unit/navegador/test_ferramentas_browser.py`.

## Extra: várias delegações ao Claude Code (ADR-0054 emenda)

`delegacoes_por_objetivo` (padrão 10) no `delegar.toml`; `Objetivo.delegacao_aprovada`: um sim por
objetivo; o guarda D pede o sim de novo fora do eixo; objetivo novo aprova de novo.
`tests/unit/delegacao/`.

## O que NÃO foi provado em máquina real

- A sala, o microfone, a caixa e a voz do dono: tudo foi provado com áudio sintético e ASR falso. Na
  contínua **sem** o detector, a fala da TV que passar no portão de eco também corta a fala do Jarvis
  (já virava pedido com ele calado) — o remédio é ligar o detector.
- O `claude -p` real seguindo a persona v16 e montando HTML com o guia.
- A janela no KDE Wayland do dono (as capturas são offscreen, backend `software`).
- A extensão recarregada com `tabs.close` no Brave dele.
- O Claude Code real fazendo várias delegações seguidas na conta dele.
- A pergunta que surge **no meio do primeiro passo do turno** (o risco dinâmico antes de o trabalho
  ir para a tarefa) ainda é só no clique — com o escopo, só para o que está fora dele.

## Para quem pegar daqui

- `verificar.py` inteiro não foi rodado (o dono roda). Rodados: ruff, mypy e as suítes de voz, s2,
  agentd, executor, política, gui, tarefas, tela, delegação, navegador, manifesto e cancelamento.
- Enquanto este lote rodava, outra CLI trabalhava no registro de provedores (ADR-0056): alguns testes
  que montam o `Aplicativo` com `s2 = "eco"` falharam por um `licenses/provedores-de-modelo.toml` que
  ela ainda não tinha criado — não são deste lote.
- Memórias gravadas: o corte de verdade (causas e onde mora) e a tela (o que o Qt faz de verdade).
