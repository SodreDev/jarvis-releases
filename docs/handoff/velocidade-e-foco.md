# Handoff — velocidade, foco por monitor, Brave e a aba que abria e fechava (2026-10-21)

Pedido do dono depois de testar a versão do `1d8dd13` (Ryzen 5 5600G, 32 GB, RTX 4060 8 GB, dois
monitores, KDE Plasma/KWin no Wayland, Brave com a extensão): (1) a aba que abre e fecha sozinha no
começo da tarefa e o passo a passo que demora; (2) "abre o Brave" falha; (3) o Brave em foco no
monitor principal não é identificado; (4) precisa ser muito rápido, medido por etapa; (5) abrir,
fechar e encerrar apps liberados seguem funcionando, e o caminho rápido não atropela o PDP.

## As causas, medidas

| sintoma | causa | onde se viu |
|---|---|---|
| aba abre e fecha; passo a passo ~14 s depois | o `web.buscar` sem chave lia numa aba de fundo do navegador do dono e a fechava; era o 1º passo de toda tarefa de site; depois, o id de uma aba velha → "falha" (extensão de antes do `1565698`), uma rodada do motor por erro | trilha do dono 21/10 21:12–21:20 (5 buscas, 5 navegações com erro) |
| "abre o Brave" falha | (a) com site junto, o roteador tirava o `browser.launch`; (b) Brave aberto: a extensão não consegue trazer a janela no Wayland; (c) app lançado sem `KDE_SESSION_VERSION` → Chromium lê "KDE4" | trilha 21:12 (`metodo_de_fora`); código; `base/nix/xdg_util.cc` |
| Brave na frente do principal não visto | a porta só sabia a janela ativa (a do teclado), sem monitor nem pilha; e sem janela ativa a lista inteira vinha vazia | KWin 6.7.5 virtual, 2 monitores (`tools/harness_foco.py`) |
| lento | o motor: 1º token ~3,3 s (p95 ~9,4 s); toda ferramenta virava tarefa; conexão nova à nuvem a cada pedido (~70 ms na ElevenLabs) | `docs/medicoes/velocidade-pedido.md` |

## Commits (autor do dono, sem coautoria, sem push)

- `765b9cf` roteador: site específico × busca genérica, `browser.launch` fica quando o dono pede o
  navegador. **Atenção:** esse commit levou junto a deleção do `jarvis/navegador/busca.py` e do teste
  dele (estavam no índice por um `git rm`); o executor só deixa de importá-lo no `81870c7` — entre os
  dois, o `src/` não importa. Não reescrevi o histórico (regra do dono).
- `81870c7` busca genérica direta (DuckDuckGo HTML) e o `tab_id` velho que não derruba a navegação.
- `774292d` janelas por monitor (`kdotool kwinscript`), `window.focused`, `KDE_SESSION_VERSION` do
  `kdotool`, `tools/harness_foco.py`, `tools/diagnostico_foco.py`, `docs/medicoes/foco-kwin-virtual.md`.
- `8b1c1ad` caminho rápido (ADR-0045): `jarvis.politica.atalho` + passo 0 do cérebro + trilha + config.
- `e359740` Brave: foco pelo KWin quando a extensão não traz; ambiente do app lançado com as
  variáveis do desktop.
- `ca7b485` conexão persistente com a Groq e a ElevenLabs (`ConexoesPersistentes`) e `aquecer()`.
- `80546bf` etapas na trilha, `tools/medir_velocidade.py`, `docs/medicoes/velocidade-pedido.md`,
  threads do embedding pela máquina.
- (este) docs: ADR-0045, emendas da 0033, 0035, 0036, 0037, COMO-TESTAR §0.29–§0.32 e este handoff.

## Onde mora cada peça

- **Caminho rápido:** `src/jarvis/politica/atalho.py` (regras: `achar`, frases: `frase`; o termo da
  busca sai da fala original por um mapa de posições), `src/jarvis/politica/sites.py` (a tabela de
  sites, também do roteador), `ExecutorDeFerramentas.atalho` (o contexto: disponível ∧ fora do
  método, o resolvedor com `LIMIAR_DO_ATALHO` 0,85, o navegador configurado),
  `Cerebro.responder` (passo 0, `caminho_rapido`, `NOTA_DO_ATALHO`, `Resposta.atalho` /
  `motor_chamado` / `ms_ate_primeira_ferramenta`), `Configuracao.caminho_rapido`.
- **Busca:** `jarvis.executor.web.buscar` (API → `_duckduckgo` → Wikipédia).
- **Janelas:** `jarvis.executor.janelas` (`CONSULTA_DO_KWIN`, `estado_do_kwin`, `EstadoDasJanelas`,
  `foco_para_o_modelo`, `listar_para_o_modelo`, `focar_o_navegador`), `comandos.ambiente_do_programa`,
  `catalogo/window.focused.yaml`.
- **Brave:** `AbridorDeNavegador.focar_janela`, `CorposDoNavegador.trazer_a_frente`,
  `Aplicativo._focar_o_navegador`, `lancador.VARIAVEIS_DO_AMBIENTE`.
- **Rede:** `jarvis.voz.nuvem.ConexoesPersistentes` / `CONEXOES` / `ClienteHttp.aquecer`,
  `MotorAsrGroq.aquecer`, `MotorTtsElevenLabs.aquecer`, `voz.app._aquecer_em_segundo_plano`.
- **Medição:** trilha (`ms_ouvido`, `ms_asr`, `ms_contexto`, `ms_primeira_ferramenta`, `atalho`,
  `motor_chamado`; evento `atalho`), `tools/medir_velocidade.py`.

## Armadilhas

1. **TMPDIR longo** do orquestrador quebra ~30 testes de soquete (`AF_UNIX path too long`): rode com
   `TMPDIR=/home/sodre/.cache/jt`. O KWin virtual também: a pasta de execução fica em `~/.cache/jfr-…`.
2. **`git rm` deixa a deleção no índice** e o próximo `git commit` a leva junto, mesmo commitando
   outros caminhos: confira `git diff --cached --name-only` antes.
3. **Frase do código não passa pelo orçamento da fala** (como o aviso): passando, o orçamento a
   segurava e a «Certo, já cuido disso.» saía antes dela.
4. **Um teste que monta o app inteiro com motor roteirizado** agora não vê o motor nos comandos
   simples (o caminho rápido vem ligado na configuração): `test_janela_abrir_apps.py` e
   `test_tarefa_do_pedido_no_app.py` foram ajustados; quem quiser o motor em tudo liga
   `caminho_rapido=False`.
5. **4xx fecha a conexão do pool** (só a que terminou bem volta): medir reaproveitamento precisa de
   um endereço que responda 200 sem chave (`api.groq.com/`, `api.elevenlabs.io/health`).
6. **O `kdotool` sai 1 sem `KDE_SESSION_VERSION=6`** e o `getactivewindow` estoura com a ativa
   `null`: as duas coisas pareciam "o Jarvis não vê janela".
7. **O KWin virtual:** `dbus-run-session -- kwin_wayland --virtual --xwayland --output-count 2 …
   --exit-with-session <script>` com o ambiente montado do zero (nada do dono passa); `KWIN_COMPOSE=Q`.

## O que o dono faz

1. `brave://extensions` → **Recarregar** a extensão do Jarvis (a trilha mostra a de antes).
2. Reiniciar o `uv run jarvis`.
3. Rodar `uv run --frozen python tools/diagnostico_foco.py` com o Brave na frente do principal e outra
   janela ativa no segundo monitor; colar o resultado.
4. Testar "abre o Discord", "fecha o Discord", "o que está em foco?", "abre o Brave" (com ele
   aberto atrás), "pesquisa vídeos de gatos no YouTube", "busca na internet quem inventou o rádio".
5. Decidir: um modelo menor para o motor (`modelo_do_s2 = "haiku"` ou `"sonnet"`: o 1º token é a
   etapa cara — `docs/medicoes/f2-02-piso-do-claude.md`); e se quer o Whisper local na GPU (pede as
   bibliotecas CUDA da NVIDIA, licença própria; na CPU ele leva ~1,4 s por fala, mais lento que a
   Groq).

## Não provado

O caminho rápido de ponta a ponta no desktop do dono (os tempos das ferramentas são da trilha dele;
a soma é composição); o KWin, os monitores e o Brave de verdade (provado no KWin virtual com janelas
Qt); o efeito do `KDE_SESSION_VERSION` no chaveiro do perfil dele; o DuckDuckGo de verdade em uso
contínuo; a conexão persistente nos turnos dele (a trilha nova vai mostrar o 1º áudio).
