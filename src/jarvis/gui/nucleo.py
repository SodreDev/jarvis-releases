"""A fronteira entre a janela e o laço de voz (ADR-0019) — e ela não tem nada de Qt.

**O que este arquivo é.** O laço de voz (`jarvis.voz.app.Aplicativo`) é síncrono: ele tica o
microfone, transcreve, responde e toca, tudo em sequência, porque é assim que o epoch tem um
dono só. Uma interface gráfica não pode chamar isso na thread que desenha — a janela
congelaria no primeiro turno. Então o laço roda numa thread de trabalho, e esta classe é a
caixa de correio entre as duas: comandos entram (segurar, soltar, digitar, interromper,
parar), e o que acontece sai por três funções (linha, estado, fim).

**Por que não tem Qt aqui.** Duas razões práticas: o teste desta parte roda sem tela nenhuma
e sem `QApplication`, e a regra "a janela é só apresentação" fica verificável por `import` —
se um dia alguém puser uma chamada de motor na tela, o teste de fronteira cai.

**O que acontece quando o áudio não vai.** Não existe "janela quebrada": se o dispositivo não
abre (sem PortAudio, sem microfone, sem permissão), a sessão **cai para o modo texto** com a
frase do que faltou e continua funcionando — é a mesma degradação declarada do F1-14, no
lugar onde o dono a vê.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.microfone import EstadoDaFonte, ler_estado
from jarvis.voz.app import Aplicativo, AplicativoIndisponivel
from jarvis.voz.config import Configuracao
from jarvis.voz.estado import Estado
from jarvis.voz.teclado import ESPACO

PARAR: Final = "\x00parar"
"""Sentinela da fila de texto: o modo texto termina quando ela chega, sem `q` nenhum."""


def _nada(_: object) -> None:
    return None


@dataclass(slots=True)
class TecladoDaJanela:
    """O botão da janela entra pelo mesmo buraco que a tecla do terminal.

    O laço já sabe o que fazer com uma tecla: espaço interrompe, `q` sai (`jarvis.voz.teclado`).
    Reaproveitar isso — em vez de criar um segundo caminho de interrupção para a janela —
    é o que mantém **um** jeito de cancelar, que é o que o F1-11 cobra em vinte pontos.

    `deque.append`/`popleft` são atômicos, então a janela escreve de uma thread e o laço lê de
    outra sem trava nenhuma.
    """

    teclas: deque[str] = field(default_factory=deque)

    def apertar(self, tecla: str) -> None:
        self.teclas.append(tecla)

    def tecla(self) -> str | None:
        try:
            return self.teclas.popleft()
        except IndexError:
            return None


@dataclass(slots=True)
class SessaoDeVoz:
    """Uma conversa em curso: a thread do laço, a caixa de entrada e as três saídas."""

    configuracao: Configuracao
    raiz: Path
    ambiente: Mapping[str, str] | None = None
    ao_linha: Callable[[str], None] = _nada
    """Cada linha que o laço escreveria no terminal. Chamada **da thread de trabalho**."""
    ao_estado: Callable[[Estado], None] = _nada
    ao_terminar: Callable[[str], None] = _nada
    """Fim da sessão: frase do erro, ou vazio quando terminou porque mandaram parar."""
    modo_texto: bool = False
    """Começa no modo texto (sem abrir dispositivo). Vira verdadeiro sozinho se o áudio cair."""

    aplicativo: Aplicativo | None = None
    teclado: TecladoDaJanela = field(default_factory=TecladoDaJanela)
    _textos: queue.SimpleQueue[str] = field(default_factory=queue.SimpleQueue, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _apertado: bool = False
    _parando: bool = False

    # --- o que a janela chama ------------------------------------------------------------
    def iniciar(self, aplicativo: Aplicativo | None = None) -> None:
        """Monta o laço e sai de perto: daqui em diante quem o conduz é a thread.

        `aplicativo` existe para quem já tem um montado — o teste, uma medição. As portas da
        ADR-0019 são ligadas nele do mesmo jeito, para o caminho testado ser o de produção.
        """
        if self.viva:
            return
        self._parando = False
        self.teclado = TecladoDaJanela()
        self._textos = queue.SimpleQueue()
        self.aplicativo = self._ligar(aplicativo or self._montar())
        self._thread = threading.Thread(target=self._trabalhar, name="jarvis-voz", daemon=True)
        self._thread.start()

    def _montar(self) -> Aplicativo:
        return Aplicativo(configuracao=self.configuracao, raiz=self.raiz, ambiente=self.ambiente)

    def _ligar(self, aplicativo: Aplicativo) -> Aplicativo:
        """Liga as três portas da ADR-0019 (mais a tela e o teclado) no laço."""
        aplicativo.escrever_na_tela = self.ao_linha
        aplicativo.teclado = self.teclado
        aplicativo.ao_mudar_estado = self.ao_estado
        aplicativo.pressionado = self._pressionado if self.configuracao.escuta == "ptt" else None
        aplicativo.texto_digitado = self._texto_pendente
        return aplicativo

    @property
    def viva(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def segurar(self) -> None:
        """O dono apertou o botão de falar (ou a barra de espaço).

        Além de abrir o turno no PTT, isto **interrompe** o Jarvis se ele estiver falando: é a
        mesma tecla de barge-in do terminal, pelo mesmo caminho.
        """
        self._apertado = True
        self.teclado.apertar(ESPACO)

    def soltar(self) -> None:
        self._apertado = False

    def interromper(self) -> None:
        self.teclado.apertar(ESPACO)

    def digitar(self, texto: str) -> None:
        linha = texto.strip()
        if linha:
            self._textos.put(linha)

    def parar(self) -> None:
        """Pede o fim pela porta normal: a mesma tecla de saída que o terminal usa.

        Não há `kill` de thread aqui, e é de propósito — o laço fecha a fonte, fecha o
        sumidouro e publica o indicador apagado no caminho de saída dele. Matar a thread
        deixaria o dispositivo aberto e o indicador aceso, que é a mentira do F1-13.
        """
        self._parando = True
        self._apertado = False
        self.teclado.apertar("q")
        self._textos.put(PARAR)

    def esperar(self, segundos: float = 5.0) -> bool:
        """Espera a thread terminar. Devolve se ela terminou mesmo (para o fechar da janela)."""
        if self._thread is None:
            return True
        self._thread.join(timeout=segundos)
        return not self._thread.is_alive()

    def estado_do_microfone(self) -> EstadoDaFonte:
        """O indicador do F1-13: o que a fonte **está** fazendo, lido de quem a tem na mão."""
        return ler_estado(self.raiz)

    # --- o que o laço chama (thread de trabalho) ------------------------------------------
    def _pressionado(self) -> bool:
        return self._apertado

    def _texto_pendente(self) -> str | None:
        try:
            linha = self._textos.get_nowait()
        except queue.Empty:
            return None
        if linha == PARAR:
            self.teclado.apertar("q")
            return None
        return linha

    def _linhas_digitadas(self) -> Iterator[str]:
        """O modo texto lendo da fila em vez de `stdin`. Bloqueia na fila, não na tela."""
        while True:
            linha = self._textos.get()
            if linha == PARAR:
                return
            yield linha

    def _trabalhar(self) -> None:
        assert self.aplicativo is not None
        erro_final = ""
        try:
            if self.modo_texto:
                self.aplicativo.rodar_texto(self._linhas_digitadas())
            else:
                self._laco_de_audio()
        except AplicativoIndisponivel as erro:
            erro_final = str(erro)
        except Exception as erro:  # a janela não pode morrer calada nem levar o processo junto
            erro_final = f"{type(erro).__name__}: {erro}"
        finally:
            self.ao_terminar(erro_final)

    def _laco_de_audio(self) -> None:
        assert self.aplicativo is not None
        try:
            self.aplicativo.rodar_audio()
        except AplicativoIndisponivel as erro:
            if self._parando:
                raise
            self.modo_texto = True
            self.ao_linha(f"sem áudio: {erro}")
            self.ao_linha("Continuo por escrito: digite abaixo e tecle Enter.")
            self.aplicativo.rodar_texto(self._linhas_digitadas())
