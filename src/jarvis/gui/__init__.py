"""gui — a janela do aplicativo (ADR-0019).

Responsabilidade: **apresentar**. Mostrar em que pé o laço está, deixar o dono segurar para
falar, parar, digitar, escolher motores e ler o diagnóstico.

Proibições, e elas são verificadas por teste (`tests/unit/gui/test_fronteira.py`):

- não fala com ASR, TTS, dispositivo de áudio nem serviço de nuvem — quem fala é
  `jarvis.voz.app`, o mesmo núcleo do `jarvis-voz`;
- não decide nada sobre epoch, cancelamento ou turno;
- não lê valor de chave de API: mostra "definida" ou "ausente" e guarda no chaveiro do
  sistema, sem nunca trazer o valor para a tela nem para o log;
- não faz trabalho pesado na thread da interface: o laço mora numa thread de trabalho
  (`jarvis.gui.nucleo`), e a janela só recebe sinais.
"""
