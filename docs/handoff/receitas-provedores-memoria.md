# Handoff — receitas das ferramentas, provedor sem mistério e a auditoria da memória (2026-10-30)

Continuação de `docs/handoff/robustez-da-ponte-e-recuperacao.md` (fatias 1 e 2). Commits na
`reescrita`: 99678ff (3), 2b0a5d6 (4) e o da auditoria (5).

## (3) Receitas — ADR-0047 emendada, COMO-TESTAR §0.51

- `src/jarvis/s2/receitas.py`: `RECEITAS` (uma por família, com as ferramentas que cada linha usa),
  `familias_do_pedido` (método da ADR-0035 + palavras + classificador opcional), `receitas_do_turno`
  (até 2 famílias, teto de 1 600 caracteres, linha com ferramenta desligada sai).
- `src/jarvis/s2/cerebro.py`: `_receitas` logo depois da nota do método; `classificador_de_receitas`
  (o app **não** liga — custaria uma ida ao Jev por turno).
- Medido: `tools/medir_receitas.py` → `docs/medicoes/receitas-sob-demanda.md` (+161 tokens em média
  só nos turnos com receita; 0 na conversa; ≤ 0,2 ms). A persona não foi mexida (outra CLI).
- Armadilha: a ferramenta que a receita cita tem de existir no catálogo **da sessão**
  (`catalogo_para_o_modelo`); o executor de teste sem memória não tem `memoria.*` e a receita some.

## (4) Provedor sem mistério — ADR-0056 emendada, COMO-TESTAR §0.53

- Causa: `Ponte.ligarNuvem` mudava só a configuração da janela; a conversa aberta montava os
  `Provedores` uma vez. Agora `FonteDePresets.nuvem` (montada em `PonteDeModelos.da_janela` com a
  configuração viva) é lida a cada pedido por `MotorDosPresets.acompanhar_a_nuvem` e pela
  `TrocaPorVoz`. **Não** mexi em `gui/ponte.py` (outra CLI trabalhava nele).
- `src/jarvis/provedores/bloqueio.py`: `Bloqueio(o_que, por_que, como, voz, codigo)`; o roteador fala
  a curta (`Texto`) e põe a inteira no `Fim(ERRO)` (tela, card e trilha).
- `PonteDeModelos.conferir(...)` + o `Repeater` «assistenteDoPreset» no `PainelDeModelos.qml`. A
  chave vem da sondagem que já roda numa thread (nunca lê chaveiro na linha da janela).
- Teste: `tests/unit/gui/test_assistente_de_preset.py` (offscreen).

## (5) Auditoria da memória — ADR-0026 emendada, COMO-TESTAR §0.54

- Relatório: `docs/medicoes/memoria-auditoria.md` (tabela, latência, plano M1–M7 para aprovar).
- Medição: `tools/medir_memoria.py` → `docs/medicoes/memoria-consulta.md`.
- Ligado: `EmbedderE5.aquecer_em_segundo_plano` (com trava) em `memoryd/conversa.py`.
- Achados que pedem decisão do dono: o histórico nunca vai ao modelo de nuvem (M2); o limiar
  calibrado está desligado e ligá-lo como está piora a abstinência (M4 depois do reranker M3); o
  Jev filtrando memória contraria a ADR-0024/0026 (M6).

## Armadilhas da sessão

- O índice do git é compartilhado com a outra CLI: stage + commit num comando só; arquivos
  compartilhados por blob HEAD+meus trechos (`git hash-object -w` + `git update-index --cacheinfo`).
- A outra CLI usa a §0.52 do COMO-TESTAR (tom de voz); a minha de provedor é a §0.53.
- `tests/unit/voz/test_app.py::test_modo_texto_responde_e_sintetiza` já falha no HEAD 9185033.

## Não provado em máquina real

Groq com a chave do dono; o painel na tela dele; o efeito das receitas no `claude -p`; a latência da
memória com o app inteiro rodando; o livro de memória real do dono (não foi lido).
