# Checklist N-dono — Fase 2 (KDE Plasma / Wayland real)

Roteiro manual (~10 min) para o dono rodar numa sessão REAL do KDE
Plasma em Wayland, antes do merge da fase 2. Cada item tem o passo e o
resultado esperado. Marque `[x]` ao concluir; se algo falhar, anote o
item e siga para "Coletar logs" no fim.

Pré-requisito: `python main.py` rodando fora de container, sessão
Wayland do Plasma ativa (`echo $XDG_SESSION_TYPE` → `wayland`).

## 1. Atalho global (portal) — PTT

- [ ] Ao abrir o Jarvis pela primeira vez nesta conta, deve aparecer um
  diálogo do sistema (xdg-desktop-portal) pedindo para autorizar o
  atalho global **Meta+Shift+G**.
  - Esperado: diálogo do Plasma com o nome do app (Jarvis/JARVIS) e o
    atalho pedido. Aceitar.
  - Se NÃO aparecer diálogo nenhum e o atalho simplesmente funcionar:
    ok também (pode já estar concedido de uma sessão anterior — ver
    "Configurações do Sistema → Atalhos → Atalhos Globais").
- [ ] Pressionar e segurar **Meta+Shift+G**: o Jarvis deve entrar em
  modo "ouvindo" (indicação visual de gravação).
- [ ] Soltar o atalho: o Jarvis deve parar de gravar e começar a
  processar o áudio.

## 2. Bandeja do sistema

- [ ] Deve aparecer um ícone do Jarvis na bandeja do sistema (system
  tray) do Plasma.
- [ ] Clique direito no ícone: menu com **Restaurar JARVIS**, **Briefing**
  e **Encerrar**.
- [ ] "Restaurar JARVIS" traz a janela principal para frente.
- [ ] "Encerrar" fecha o Jarvis (usar por último, ou reabrir depois).

## 3. Notificação

- [ ] Disparar uma notificação do Jarvis (ex.: pedir um briefing, ou
  qualquer ação que gere aviso).
  - Esperado: notificação nativa do Plasma (canto da tela, com ícone e
    texto do Jarvis), não uma janela própria.

## 4. Volume e mute do microfone

- [ ] Pedir para o Jarvis subir/abaixar o volume do sistema.
  - Esperado: volume muda de fato (conferir no widget de som do
    Plasma).
- [ ] Pedir para o Jarvis silenciar/dessilenciar o microfone.
  - Esperado: estado do mic muda (conferir no widget de som/indicador
    de mic do Plasma).

## 5. Área de transferência com histórico

- [ ] Copiar 2-3 textos diferentes (Ctrl+C em lugares distintos).
- [ ] Pedir ao Jarvis o histórico do clipboard.
  - Esperado: os textos copiados aparecem, na ordem certa (mais
    recente primeiro ou como o Jarvis sempre mostrou no Windows).

## 6. Mídia (MPRIS) — play/pause/next

- [ ] Abrir um player MPRIS (Spotify, ou uma aba do navegador tocando
  vídeo/música).
- [ ] Pedir ao Jarvis para pausar.
  - Esperado: o player pausa.
- [ ] Pedir para tocar de novo.
  - Esperado: o player retoma.
- [ ] Pedir para pular/próxima faixa (se o player suportar).
  - Esperado: player avança.

## 7. Abrir documento/imagem gerado

- [ ] Pedir ao Jarvis para gerar e abrir um documento (ex.: um PDF ou
  imagem que ele cria).
  - Esperado: abre no aplicativo padrão do sistema (visualizador de
    PDF/imagens do Plasma), sem erro.

## 8. Restart em modo dev

- [ ] Com o Jarvis rodando em modo dev (F5 ou o atalho de reload que
  o Windows usava), pedir/forçar um restart.
  - Esperado: o processo reinicia limpo, sem janela travada, sem
    processo órfão sobrando (`ps aux | grep -i main.py` só mostra a
    instância nova).

## Coletar logs se algo falhar

Sem nenhum segredo — apagar tokens/chaves de API antes de compartilhar.

- `crash.log` na raiz do projeto (se existir, tem o traceback Python).
- `crash_native.log` na raiz do projeto (crash nativo, ex.: Qt/WebEngine).
- stdout/stderr do terminal onde `python main.py` foi rodado (rolar
  para trás ou redirecionar: `python main.py 2>&1 | tee /tmp/jarvis-run.log`).
- `journalctl --user -b --since "-15 min"` para ver se o
  xdg-desktop-portal, o KGlobalAccel ou o D-Bus de sessão registraram
  algum erro relacionado ao Jarvis.
- Anotar qual item do checklist falhou e em qual passo exato, para
  reproduzir mais fácil.
