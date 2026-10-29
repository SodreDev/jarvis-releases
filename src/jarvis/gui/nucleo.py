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
from typing import Any, Final

from jarvis.microfone import EstadoDaFonte, ler_estado
from jarvis.voz.app import Aplicativo, AplicativoIndisponivel, OuvidoIndisponivel
from jarvis.voz.config import Configuracao
from jarvis.voz.conversa import ConversaPersistente
from jarvis.voz.escuta import Escuta
from jarvis.voz.estado import Estado
from jarvis.voz.teclado import ESPACO
from jarvis.voz.vocabulario import RepositorioDoVocabulario

PARAR: Final = "\x00parar"
"""Sentinela da fila de texto: o modo texto termina quando ela chega, sem `q` nenhum."""
TIQUE_SEM_TEXTO_S: Final = 0.25
"""Sem nada digitado, de quanto em quanto o modo texto olha a fila de avisos."""


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
    ao_encerrar: Callable[[], None] = lambda: None
    """O dono pediu para encerrar o Jarvis (`jarvis.encerrar`, ADR-0041) e o laço saiu limpo: quem
    abriu a sessão fecha o aplicativo. Chamada da thread de trabalho, depois de `ao_terminar`."""
    ao_mudar_avisos: Callable[[], None] = lambda: None
    ao_pedaco: Callable[[str], None] = _nada
    ao_pedir_confirmacao: Callable[[Any], None] = _nada
    """O laço quer a confirmação do dono para uma ferramenta (ADR-0028). Da thread de trabalho."""
    ao_fim_da_confirmacao: Callable[[str], None] = _nada
    """A resposta em stream: o texto acumulado a cada pedaço de fala (ADR-0025). Da thread de
    trabalho, como as outras."""
    """A fila de avisos do laço mudou (ADR-0025). Chamada da thread de trabalho."""
    ao_mudar_tarefas: Callable[[], None] = lambda: None
    ao_mudar_navegador: Callable[[bool], None] = lambda _ativo: None
    """O Jarvis passou a controlar (ou soltou) uma aba do navegador: a janela mostra o PARAR."""
    ao_mostrar_conteudo: Callable[[Any], None] | None = None
    """O Jarvis montou uma exibição (`tela.mostrar`, ADR-0055). Da thread de quem pediu. `None` =
    sem tela: as `tela.*` não existem para o modelo."""
    ao_fechar_conteudo: Callable[[str], None] | None = None
    """Uma tarefa em segundo plano mudou (ADR-0022). Chamada da linha **da tarefa**."""
    escuta: Escuta | None = None
    """O modo de escuta vivo, de quem abriu a sessão (a ponte). Trocá-lo vale no próximo tique
    do laço, sem reiniciar nada (ADR-0021). `None` = o laço monta um da configuração."""
    avisos_dados: set[str] = field(default_factory=set)
    """Os avisos de privacidade já ditos; quem abre as sessões (a ponte) passa o mesmo conjunto
    a todas, e o texto longo não volta a cada conversa."""
    conversa: ConversaPersistente | None = None
    """A conversa que sobrevive ao reinício (a ponte a abre uma vez e passa a todas as sessões)."""
    vocabulario: RepositorioDoVocabulario | None = None
    """O vocabulário do dono (ADR-0044), que a ponte passa a cada sessão."""
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
        return Aplicativo(
            configuracao=self.configuracao,
            raiz=self.raiz,
            ambiente=self.ambiente,
            conversa=self.conversa,
            vocabulario=self.vocabulario,
        )

    def _ligar(self, aplicativo: Aplicativo) -> Aplicativo:
        """Liga as três portas da ADR-0019 (mais a tela e o teclado) no laço."""
        aplicativo.escrever_na_tela = self.ao_linha
        aplicativo.avisos_dados = self.avisos_dados
        aplicativo.teclado = self.teclado
        aplicativo.ao_mudar_estado = self.ao_estado
        aplicativo.ao_mudar_avisos = self.ao_mudar_avisos
        aplicativo.ao_mudar_tarefas = self.ao_mudar_tarefas
        aplicativo.ao_mudar_navegador = self.ao_mudar_navegador
        aplicativo.ao_pedaco = self.ao_pedaco
        if self.ao_mostrar_conteudo is not None and self.ao_fechar_conteudo is not None:
            aplicativo.ao_mostrar_conteudo = self.ao_mostrar_conteudo
            aplicativo.ao_fechar_conteudo = self.ao_fechar_conteudo
        aplicativo.ao_pedir_confirmacao = self.ao_pedir_confirmacao
        aplicativo.ao_fim_da_confirmacao = self.ao_fim_da_confirmacao
        # A porta do dedo fica **sempre** ligada: o modo troca com a sessão aberta, e quem
        # decide se o dedo manda é o laço, pelo modo vivo — não esta montagem.
        aplicativo.pressionado = self._pressionado
        if self.escuta is not None:
            aplicativo.escuta = self.escuta
        aplicativo.texto_digitado = self._texto_pendente
        if aplicativo.conversa is None:
            aplicativo.conversa = self.conversa
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

    def parar_navegador(self) -> None:
        """O PARAR do navegador na janela (ADR-0027 regra 4): solta as abas e cancela o turno e as
        tarefas que estavam nelas. Numa linha à parte: falar com a extensão não trava a janela."""
        aplicativo = self.aplicativo
        if aplicativo is None:
            return
        threading.Thread(
            target=aplicativo.parar_navegador, name="jarvis-parar-navegador", daemon=True
        ).start()

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

    def responder_confirmacao(self, identificador: str, sim: bool) -> bool:
        """O clique do dono numa confirmação de ferramenta, levado ao laço que espera."""
        if self.aplicativo is None:
            return False
        return self.aplicativo.responder_confirmacao(identificador, sim)

    def dados_das_tarefas(self) -> dict[str, list[dict[str, str]]]:
        """Os itens do card `tarefas`; antes de haver laço, não há tarefa."""
        if self.aplicativo is None:
            return {"itens": []}
        return self.aplicativo.dados_das_tarefas()

    def parar_tarefa(self, tarefa_id: str) -> bool:
        """O "parar" do card: o dono, com o dedo."""
        return self.aplicativo is not None and self.aplicativo.parar_tarefa(tarefa_id)

    def conteudo_fechado_pelo_dono(self, identificador: str) -> None:
        """O dono fechou na janela uma exibição que o Jarvis montou (ADR-0055)."""
        if self.aplicativo is not None:
            self.aplicativo.conteudo_fechado_pelo_dono(identificador)

    def dados_dos_avisos(self) -> dict[str, list[dict[str, str]]]:
        """O card `notificacoes`: a fila do laço, ou vazia antes de haver laço."""
        if self.aplicativo is None:
            return {"avisos": []}
        return self.aplicativo.dados_dos_avisos()

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

    def _linhas_digitadas(self) -> Iterator[str | None]:
        """O modo texto lendo da fila em vez de `stdin`. Bloqueia na fila, não na tela; sem nada
        digitado, um `None` a cada `TIQUE_SEM_TEXTO_S` deixa o laço dar voz ao aviso que espera
        o piso livre (a resposta de uma tarefa, ADR-0038)."""
        while True:
            try:
                linha = self._textos.get(timeout=TIQUE_SEM_TEXTO_S)
            except queue.Empty:
                yield None
                continue
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
            if erro_final:
                # O card de avisos guarda o que derrubou a conversa: a linha da transcrição
                # rola para fora da tela, o card fica (ADR-0025, "nada some sem rastro").
                self.aplicativo.registrar_aviso(
                    "falhou", "conversa", f"a conversa parou: {erro_final}"
                )
            self.ao_terminar(erro_final)
            if self.aplicativo.encerrado:
                self.ao_encerrar()

    def _laco_de_audio(self) -> None:
        assert self.aplicativo is not None
        try:
            self.aplicativo.rodar_audio()
        except AplicativoIndisponivel as erro:
            if self._parando:
                raise
            self.modo_texto = True
            if isinstance(erro, OuvidoIndisponivel):
                # Bug do dono (2026-10-16): com o ASR da nuvem desligado, a janela caía no modo
                # texto dizendo "sem áudio", e a voz dele "não saía". O que falta é o ouvido,
                # e o caminho tem de estar na frase — e no card, que não rola para fora.
                frase = (
                    f"não estou ouvindo: {erro}. Para falar comigo, ligue esse ASR em "
                    "Configuração → Voz — ouvir (e salve), ou escolha asr-whisper-local, que "
                    "roda na máquina."
                )
                self.ao_linha(frase)
                self.aplicativo.registrar_aviso("falhou", "ouvir", frase)
            else:
                self.ao_linha(f"sem áudio: {erro}")
            self.ao_linha("Continuo por escrito: digite abaixo e tecle Enter.")
            self.aplicativo.rodar_texto(self._linhas_digitadas())
