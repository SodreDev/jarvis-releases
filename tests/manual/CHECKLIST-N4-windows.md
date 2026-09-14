# Checklist N4 — Windows real (antes do merge)

Roteiro para rodar numa máquina Windows real (não container, não VM
headless) antes de fazer o merge de `linux-port` para a branch
principal. Cobre a FILA da fase 1 e da fase 2. Marque `[x]` ao
concluir; se algo falhar, anote o item e colete os logs no fim.

## 0. Suíte automatizada

- [ ] `pytest -m "not linux_only and not x11 and not wayland"`
  - Esperado: só os testes que fazem sentido no Windows rodam (C
    windows, K resolvidos pela versão win32, nada `linux_only`/
    `x11`/`wayland`), tudo verde.

## 1. Atalho global (PTT) — Shift+G

- [ ] Pressionar e segurar **Shift+G** em qualquer janela em foco:
  Jarvis entra em modo "ouvindo".
- [ ] Soltar: para de gravar e processa o áudio.

## 2. Os 4 atalhos configurados

- [ ] Testar os 4 atalhos globais configurados em `hotkeys` (ex.:
  ação rápida, abrir/fechar janela, etc. — conferir a lista real em
  `config.json`/equivalente do usuário de teste). Cada um deve disparar
  a ação certa mesmo com o Jarvis em segundo plano.

## 3. Bandeja do sistema (tray)

- [ ] Ícone do Jarvis aparece na bandeja (perto do relógio).
- [ ] Clique direito: menu com Restaurar JARVIS / Briefing / Encerrar,
  igual ao Linux.
- [ ] Restaurar traz a janela pra frente; Encerrar fecha limpo.

## 4. F5 (reload) x10

- [ ] Com o Jarvis em modo dev, apertar F5 (reload) 10 vezes seguidas.
  - Esperado: nenhum crash, nenhuma janela fantasma sobrando, memória
    não dispara sem parar (uso de RAM estável entre reloads).

## 5. TTS sem janela piscando

- [ ] Pedir uma resposta falada (TTS) e observar a tela inteira
  enquanto ele fala.
  - Esperado: nenhuma janela de console/terminal piscando/aparecendo
    e sumindo durante a síntese de voz.

## 6. Sem msedgewebview2.exe órfão

- [ ] Fechar o Jarvis normalmente (Encerrar pelo tray ou pela janela).
- [ ] Abrir o Gerenciador de Tarefas e conferir processos.
  - Esperado: nenhum `msedgewebview2.exe` (ou processo filho do
    pywebview) sobrando depois que o Jarvis fechou.

## 7. Clipboard 10 min sem access violation

- [ ] Deixar o Jarvis rodando com o monitor de clipboard ativo por 10
  minutos, copiando textos e imagens variados nesse intervalo (uso
  normal do PC, sem forçar nada estranho).
  - Esperado: nenhum crash / access violation relacionado ao
    clipboard nesse tempo; `crash.log`/`crash_native.log` sem entrada
    nova.

## 8. Volume

- [ ] Pedir para subir/abaixar volume do sistema e mutar/desmutar o
  microfone.
  - Esperado: muda de fato (conferir no mixer de volume do Windows).

## 9. Mídia

- [ ] Com um player tocando (Spotify, navegador, etc.), pedir
  play/pause/próxima via Jarvis.
  - Esperado: player responde certo.

## 10. Restart em modo dev

- [ ] Forçar um restart em modo dev.
  - Esperado: reinicia limpo, sem janela travada, sem processo órfão
    (conferir Gerenciador de Tarefas).

## 11. Abrir PDF/imagem gerados

- [ ] Pedir ao Jarvis para gerar e abrir um PDF e uma imagem.
  - Esperado: abrem no aplicativo padrão do Windows, sem erro.

## 12. Notepad com texto longo

- [ ] Pedir ao Jarvis para escrever/colar um texto bem longo no
  Notepad (ou abrir o Notepad com um texto gerado longo).
  - Esperado: texto completo aparece corretamente, sem truncar e sem
    travar o Notepad ou o Jarvis.

## Coletar logs se algo falhar

Sem nenhum segredo — apagar tokens/chaves de API antes de compartilhar.

- `crash.log` e `crash_native.log` na raiz do projeto.
- Saída do terminal onde o Jarvis foi iniciado (se rodou via
  `python main.py`, redirecionar: `python main.py > jarvis-run.log 2>&1`).
- Visualizador de Eventos do Windows (Logs do Windows → Aplicativo) se
  houve crash reportado pelo sistema, filtrando por horário do teste.
- Anotar o item exato do checklist que falhou e o passo em que
  aconteceu, para reproduzir mais fácil.
