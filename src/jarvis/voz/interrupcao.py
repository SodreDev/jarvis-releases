"""Interromper o Jarvis por voz (dono, 2026-10-21, ADR-0040).

Até aqui só o botão interrompia: enquanto o Jarvis falava, o laço de voz tocava o áudio e **não
lia o microfone** — o dono podia gritar "Jarvis, para" que ninguém ouvia. Agora, entre um quadro de
áudio tocado e o próximo, o laço lê um quadro do microfone e o entrega à `VigiaDeInterrupcao`, que
decide se o dono falou por cima:

1. **Portão de eco** (`PortaoDeEco`): o alto-falante entra no microfone, e o VAD chama isso de fala.
   O portão compara a energia do quadro do microfone com a do que **nós** mandamos tocar (a
   referência, pelo `escuta` da fila de playback) nos últimos 300 ms, menos a perda do caminho
   alto-falante → microfone, **aprendida** enquanto só o Jarvis fala. Só passa o que é bem mais alto
   que o eco previsto **e** que o ruído do ambiente (a TV ligada antes de o Jarvis falar), e mais
   alto que um piso de fala perto do microfone. Não é cancelamento de eco (AEC): é o detector de
   fala dupla por energia, o que dá para fazer sem a referência alinhada amostra a amostra.
2. **Suspeita**: 240 ms de fala (VAD) que passou no portão. Na escuta contínua o Jarvis **pausa** na
   hora — é o que um humano faz quando alguém começa a falar — e a fila guarda o resto do lote.
3. **Conteúdo**: o trecho (com os 400 ms de antes) vai ao ASR numa linha à parte, sem prender o
   áudio, e de novo a cada 400 ms enquanto cresce. Corta quando:
   - a **palavra de ativação** está nele (nos dois modos) — e o que o próprio Jarvis está dizendo
     não é o trecho (o eco de "eu sou o Jarvis" não corta);
   - na contínua, uma **ordem de parar** curta ("para", "chega", "espera aí", "silêncio");
   - na contínua, o **detector de endereçamento** (Jev, ADR-0029, quando o dono o ligou) diz que a
     fala é com o Jarvis.
   Transcrição vazia, igual ao que o Jarvis disse (eco), ou sem nada disso: **não corta** — na
   contínua o Jarvis retoma de onde parou. Na dúvida, não age (o ruído da TV não corta).
4. **Corte**: o laço mata o epoch (a fila esvazia, o que não foi falado é cancelado, o cérebro para
   de gerar) e o áudio do trecho vira o **começo do turno novo** do dono.

Nada daqui confirma ação: o "sim" dito por cima de uma pergunta não é resposta (a pergunta não foi
ouvida inteira, ADR-0038) — quem cuida disso é o `interromper` do laço, como no botão.
"""

from __future__ import annotations

import unicodedata
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from jarvis.audio_io.quadro import MS_POR_QUADRO, PISO_DB, Quadro, energia_db
from jarvis.voz.escuta import ModoDeEscuta
from jarvis.voz.palavra import DetectorDePalavra, palavras_de

# --- o portão de eco ---------------------------------------------------------------------------
JANELA_DO_ECO_QUADROS: Final = 15
"""300 ms de referência: cobre a latência do que sai no alto-falante até voltar no microfone."""
REFERENCIA_ATIVA_DB: Final = -55.0
"""Abaixo disto a referência é silêncio: não há eco a prever (e o quadro mede o ambiente)."""
PERDA_INICIAL_DB: Final = 6.0
"""Quanto o caminho alto-falante → microfone atenua, antes de aprender: pouco (o pior caso)."""
PERDA_MINIMA_DB: Final = 0.0
PERDA_MAXIMA_DB: Final = 50.0
"""Fone de ouvido: quase nada volta. O teto evita um portão sensível demais por um quadro mudo."""
APRENDIZADO: Final = 0.05
"""Passo da média da perda por quadro de eco (≈ 400 ms para assentar)."""
APRENDIZADO_COM_FALA: Final = 0.01
"""Com o quadro acima do portão, a perda só **diminui**, e devagar: um eco que cresce de verdade
(o volume subiu) acaba aprendido, e meio segundo do dono falando quase não mexe nela."""
RECUO_POR_ECO_DB: Final = 3.0
"""Quando a transcrição confirma que o que passou era o eco do Jarvis, a perda recua isto."""
MARGEM_DO_ECO_DB: Final = 6.0
MARGEM_DO_AMBIENTE_DB: Final = 9.0
PISO_DA_FALA_DB: Final = -50.0
"""Mais baixo que isto não é alguém falando perto do microfone."""
QUADROS_DO_AMBIENTE: Final = 250
"""5 s de microfone com o Jarvis calado: é dali que sai o nível do ambiente (a TV, a rua)."""
PERCENTIL_DO_AMBIENTE: Final = 0.3

# --- a vigia -----------------------------------------------------------------------------------
FALA_PARA_SUSPEITAR_MS: Final = 240
SILENCIO_PARA_FECHAR_MS: Final = 400
QUADROS_ANTES_DA_FALA: Final = 20
"""400 ms guardados antes da suspeita: o começo da palavra de ativação."""
INTERVALO_DE_CHECAGEM_MS: Final = 400
MAXIMO_DA_CHECAGEM_MS: Final = 3000
"""Depois de 3 s de trecho sem decisão, não se pergunta de novo: decide com o que tem."""
MAXIMO_DA_PAUSA_MS: Final = 2500
"""Na contínua, pausado e sem decisão por tanto tempo, o Jarvis retoma (na dúvida, não age)."""
PALAVRAS_DO_FALADO: Final = 60
"""O que o Jarvis disse por último, para reconhecer o eco dele na transcrição."""
SEMELHANCA_DE_ECO: Final = 0.6
PALAVRAS_DA_ORDEM: Final = 5
ORDENS_DE_PARAR: Final[tuple[str, ...]] = (
    "para", "pare", "parar", "paré", "chega", "espera", "espere", "pera", "perai", "peraí",
    "silencio", "silêncio", "cala", "calado", "quieto", "cancela", "cancelar", "esquece",
    "ja entendi", "já entendi", "deixa pra la", "deixa pra lá", "nao precisa", "não precisa",
)  # fmt: skip
"""Ordens de parar que valem sem a palavra de ativação na escuta contínua: no começo de um trecho
curto. Agradecimento e "ok" ficam de fora — a TV diz isso o tempo todo."""


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.casefold().split())


def _palavras(texto: str) -> list[str]:
    return [_dobrar(p) for p in palavras_de(texto) if p]


def _percentil(valores: Sequence[float], fracao: float) -> float:
    if not valores:
        return PISO_DB
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(fracao * len(ordenados)))]


@dataclass(slots=True)
class PortaoDeEco:
    """Detector de fala dupla por energia: o quadro do microfone é o dono, ou é o eco do Jarvis?"""

    perda_db: float = PERDA_INICIAL_DB
    margem_do_eco_db: float = MARGEM_DO_ECO_DB
    margem_do_ambiente_db: float = MARGEM_DO_AMBIENTE_DB
    piso_da_fala_db: float = PISO_DA_FALA_DB
    ambiente_db: float = PISO_DB
    _referencias: deque[float] = field(
        default_factory=lambda: deque(maxlen=JANELA_DO_ECO_QUADROS), repr=False
    )
    _referencia_do_quadro: float = field(default=PISO_DB, repr=False)
    _niveis_do_ambiente: deque[float] = field(
        default_factory=lambda: deque(maxlen=QUADROS_DO_AMBIENTE), repr=False
    )

    def referencia(self, amostras: bytes) -> None:
        """O que acabou de ir para o alto-falante (o `escuta` da fila de playback)."""
        self._referencia_do_quadro = max(self._referencia_do_quadro, energia_db(amostras))

    @property
    def tocando(self) -> bool:
        return max(self._referencias, default=PISO_DB) > REFERENCIA_ATIVA_DB

    def eco_previsto_db(self) -> float:
        maior = max(self._referencias, default=PISO_DB)
        return maior - self.perda_db if maior > REFERENCIA_ATIVA_DB else PISO_DB

    def limiar_db(self) -> float:
        return max(
            self.eco_previsto_db() + self.margem_do_eco_db,
            self.ambiente_db + self.margem_do_ambiente_db,
            self.piso_da_fala_db,
        )

    def ver(self, quadro: Quadro) -> bool:
        """Um quadro de 20 ms do microfone: passou (é mais alto que o eco e o ambiente)? Aprende a
        perda com o eco e o ambiente com o silêncio do Jarvis."""
        self._referencias.append(self._referencia_do_quadro)
        self._referencia_do_quadro = PISO_DB
        nivel = quadro.energia_db
        passou = nivel >= self.limiar_db()
        maior = max(self._referencias)
        if maior > REFERENCIA_ATIVA_DB:
            observada = min(PERDA_MAXIMA_DB, max(PERDA_MINIMA_DB, maior - nivel))
            if not passou:
                self.perda_db += APRENDIZADO * (observada - self.perda_db)
            elif observada < self.perda_db:
                self.perda_db += APRENDIZADO_COM_FALA * (observada - self.perda_db)
        else:
            self._niveis_do_ambiente.append(nivel)
            self.ambiente_db = _percentil(self._niveis_do_ambiente, PERCENTIL_DO_AMBIENTE)
        return passou

    def era_o_eco(self) -> None:
        """A transcrição disse que o que passou era o Jarvis: o eco é mais alto que o previsto."""
        self.perda_db = max(PERDA_MINIMA_DB, self.perda_db - RECUO_POR_ECO_DB)


# --- a vigia ------------------------------------------------------------------------------------
class Acao(StrEnum):
    """O que o laço faz com o quadro que a vigia acabou de ouvir."""

    NADA = "nada"
    PAUSAR = "pausar"
    """Na contínua: a fila segura o áudio (sem descartar) enquanto o conteúdo é conferido."""
    RETOMAR = "retomar"
    CORTAR = "cortar"
    """O dono falou com o Jarvis por cima: o epoch morre e o trecho é o começo do turno novo."""


class Motivo(StrEnum):
    """Por que a vigia decidiu — o código que vai para a trilha (nunca o texto ouvido)."""

    PALAVRA_DE_ATIVACAO = "palavra_de_ativacao"
    ORDEM_DE_PARAR = "ordem_de_parar"
    ENDERECADA = "enderecada"
    ECO_DO_JARVIS = "eco_do_jarvis"
    SEM_FALA = "sem_fala"
    SEM_CHAMADA = "sem_chamada"
    NAO_ERA_COMIGO = "nao_era_comigo"
    PRAZO_DA_PAUSA = "prazo_da_pausa"
    SUSPEITA = "suspeita"


@dataclass(frozen=True, slots=True)
class Decisao:
    """Uma decisão da vigia, para a trilha: o que fez, por quê e quanto o trecho já tinha."""

    acao: Acao
    motivo: Motivo
    ms: float
    """Do começo do trecho suspeito até a decisão, em tempo de áudio."""


Enviar = Callable[[Callable[[], object]], "Future[object]"]
"""Roda uma função noutra linha e devolve o futuro dela (o `submit` de um executor)."""


def em_linha(funcao: Callable[[], object]) -> Future[object]:
    """Roda já, na linha de quem chama — o teste fica determinístico. No produto é uma linha à
    parte (`ThreadPoolExecutor(max_workers=1).submit`): o ASR leva centenas de milissegundos, e o
    áudio não pode parar enquanto ele roda."""
    futuro: Future[object] = Future()
    try:
        futuro.set_result(funcao())
    except BaseException as erro:  # o erro do ASR é do futuro, não de quem toca o áudio
        futuro.set_exception(erro)
    return futuro


def eh_ordem_de_parar(texto: str) -> bool:
    """Uma ordem de parar ("para", "chega", "espera aí", "silêncio") no começo de trecho curto."""
    palavras = _palavras(texto)
    if not palavras or len(palavras) > PALAVRAS_DA_ORDEM:
        return False
    junto = " ".join(palavras)
    return any(
        junto == ordem or junto.startswith(ordem + " ")
        for ordem in {_dobrar(o) for o in ORDENS_DE_PARAR}
    )


def so_ordem_de_parar(texto: str) -> bool:
    """O trecho inteiro é só uma ordem de parar ("para", "chega", "jarvis, para"): o corte já foi
    o pedido, e não há o que responder."""
    palavras = _palavras(texto)
    return bool(palavras) and len(palavras) <= 3 and eh_ordem_de_parar(texto)


@dataclass(slots=True)
class VigiaDeInterrupcao:
    """Ouve o dono enquanto o Jarvis fala (ou pensa) e decide se ele falou por cima."""

    transcrever: Callable[[bytes], str]
    """O ASR da sessão (com a trava do laço): áudio → texto."""
    palavra: DetectorDePalavra = field(default_factory=DetectorDePalavra)
    """A palavra de ativação do dono (a mesma da escuta)."""
    enderecada: Callable[[str], bool] | None = None
    """O detector de endereçamento (Jev), quando o dono o ligou: "a fala é com o Jarvis?". Só na
    contínua; `None` = sem ele, e lá só a palavra e a ordem de parar cortam."""
    enviar: Enviar = em_linha
    portao: PortaoDeEco = field(default_factory=PortaoDeEco)
    modo: ModoDeEscuta = ModoDeEscuta.PALAVRA
    decisoes: list[Decisao] = field(default_factory=list)
    """As decisões desta sessão (o laço manda cada uma para a trilha)."""

    _antes: deque[bytes] = field(
        default_factory=lambda: deque(maxlen=QUADROS_ANTES_DA_FALA), repr=False
    )
    _falado: deque[str] = field(default_factory=lambda: deque(maxlen=PALAVRAS_DO_FALADO))
    _segmento: bytearray | None = field(default=None, repr=False)
    _ms_do_segmento: float = 0.0
    _fala_ms: float = 0.0
    _silencio_ms: float = 0.0
    _suspeito: bool = False
    _pausado: bool = False
    _ms_da_pausa: float = 0.0
    _fala_checada_ms: float = 0.0
    """Quanto de fala o trecho tinha na última leitura: lê de novo só com fala nova."""
    _sem_corte: Motivo = Motivo.SEM_FALA
    """O que a última leitura achou sem cortar — o motivo de descartar, se o trecho fechar assim."""
    _futuro: Future[object] | None = field(default=None, repr=False)
    _futuro_do_detector: bool = False
    _corte: bytes = field(default=b"", repr=False)
    _contida: bool = False
    """A fala que segue é a mesma que acabou de ser julgada não ser com o Jarvis (a TV, alguém na
    sala): até ela parar, sem pausa e sem perguntar ao detector de novo — senão o Jarvis gaguejaria
    a cada 240 ms. A palavra de ativação e a ordem de parar continuam cortando."""
    _silencio_corrido_ms: float = 0.0
    _trecho_contido: bool = False
    """O trecho de agora nasceu da fala contida: ele inteiro segue a regra dela, até o fim."""

    # --- o que o laço chama --------------------------------------------------------------------
    def comecar(self, modo: ModoDeEscuta, *, palavra: DetectorDePalavra | None = None) -> None:
        """O Jarvis começou a preparar uma fala: trecho novo, com o modo e a palavra vivos de agora
        (o dono troca os dois com a sessão aberta, ADR-0021)."""
        self.modo = modo
        if palavra is not None:
            self.palavra = palavra
        self._fechar_segmento()
        self._falado.clear()
        self._contida = False
        self._silencio_corrido_ms = 0.0

    def falando(self, texto: str) -> None:
        """O lote que acabou de entrar no alto-falante: é com ele que o eco é reconhecido."""
        self._falado.extend(_palavras(texto))

    def ouvir(self, quadro: Quadro, *, fala_no_vad: bool) -> Acao:
        """Um quadro de 20 ms do microfone, com o que o VAD diz dele. Devolve o que fazer."""
        passou = self.portao.ver(quadro)
        candidato = fala_no_vad and passou
        self._silencio_corrido_ms = 0.0 if candidato else self._silencio_corrido_ms + MS_POR_QUADRO
        if self._silencio_corrido_ms >= SILENCIO_PARA_FECHAR_MS:
            self._contida = False  # aquela fala acabou: a próxima é julgada do zero
        if self._segmento is None:
            if not candidato:
                self._antes.append(quadro.amostras)
                return Acao.NADA
            self._segmento = bytearray(b"".join(self._antes))
            self._antes.clear()
            self._trecho_contido = self._contida
            self._ms_do_segmento = self._fala_ms = self._silencio_ms = 0.0
        self._segmento.extend(quadro.amostras)
        self._ms_do_segmento += MS_POR_QUADRO
        if self._pausado:
            self._ms_da_pausa += MS_POR_QUADRO
        if candidato:
            self._fala_ms += MS_POR_QUADRO
            self._silencio_ms = 0.0
        else:
            self._silencio_ms += MS_POR_QUADRO
        if not self._suspeito and self._fala_ms >= FALA_PARA_SUSPEITAR_MS:
            self._suspeito = True
            self._checar()  # a primeira leitura sai já, na suspeita
            if self.modo is ModoDeEscuta.CONTINUA and not self._trecho_contido:
                # Pausa antes do resultado: o Jarvis cala na hora, como quem ouve alguém começar a
                # falar — e o microfone fica só com o dono, sem o eco por cima.
                self._pausado = True
                self._ms_da_pausa = 0.0
                self._registrar(Acao.PAUSAR, Motivo.SUSPEITA)
                decisao = self._resultado()
                if decisao is None or decisao is Acao.NADA:
                    return Acao.PAUSAR
                return decisao
        if self._suspeito:
            return self._acompanhar()
        if self._silencio_ms >= SILENCIO_PARA_FECHAR_MS:
            self._fechar_segmento()  # ruído curto: nem chegou a suspeita
        return Acao.NADA

    def audio_do_corte(self) -> bytes:
        """O trecho que cortou o Jarvis, com os 400 ms de antes: o começo do turno novo."""
        corte, self._corte = self._corte, b""
        return corte

    def terminar(self) -> bytes:
        """A fala do Jarvis acabou sozinha. Se o dono já estava falando (um trecho com fala de
        verdade), o áudio dele volta ao laço como o começo do turno — ele não perde o que disse."""
        aproveitado = b""
        if self._segmento is not None and self._fala_ms >= FALA_PARA_SUSPEITAR_MS:
            aproveitado = bytes(self._segmento)
        self._fechar_segmento()
        return aproveitado

    def ultimos_quadros(self) -> list[bytes]:
        """Os 400 ms mais recentes fora de um trecho: o laço os usa como o "antes da fala"."""
        return list(self._antes)

    def sem_o_eco(self, texto: str) -> str:
        """O turno novo sem o começo que era o Jarvis falando: a transcrição pega o fim da fala
        dele junto com a do dono. Tira o prefixo (de duas palavras ou mais) que está no falado."""
        lidas = [(bruta, _palavras(bruta)) for bruta in texto.split()]
        pedacos = [(bruta, dobradas[0]) for bruta, dobradas in lidas if dobradas]
        falado = list(self._falado)
        if len(pedacos) < 2 or not falado:
            return texto
        dobradas = [dobrada for _bruta, dobrada in pedacos]
        corte = 0
        for tamanho in range(len(dobradas), 1, -1):
            prefixo = dobradas[:tamanho]
            if any(falado[i : i + tamanho] == prefixo for i in range(len(falado) - tamanho + 1)):
                corte = tamanho
                break
        return " ".join(bruta for bruta, _dobrada in pedacos[corte:]) if corte else texto

    # --- por dentro ----------------------------------------------------------------------------
    def _acompanhar(self) -> Acao:
        """Trecho suspeito: confere o conteúdo, decide, e fecha quando o dono para de falar."""
        decisao = self._resultado()
        if decisao is not None:
            return decisao
        fechando = (
            self._silencio_ms >= SILENCIO_PARA_FECHAR_MS
            or self._ms_do_segmento >= MAXIMO_DA_CHECAGEM_MS
        )
        nova = self._fala_ms - self._fala_checada_ms
        if self._futuro is None and (nova >= INTERVALO_DE_CHECAGEM_MS or (fechando and nova > 0)):
            # Fala nova desde a última leitura: lê o trecho inteiro de novo (no fechamento, uma
            # última vez, com tudo o que o dono disse).
            self._checar()
            decisao = self._resultado()
            if decisao is not None:
                return decisao
        if self._futuro is None and fechando:
            return self._descartar(self._sem_corte)
        if self._pausado and self._ms_da_pausa >= MAXIMO_DA_PAUSA_MS:
            return self._descartar(Motivo.PRAZO_DA_PAUSA)
        return Acao.NADA

    def _checar(self) -> None:
        if self._futuro is not None or self._segmento is None:
            return
        self._fala_checada_ms = self._fala_ms
        audio = bytes(self._segmento)
        self._futuro_do_detector = False
        self._futuro = self.enviar(lambda: self.transcrever(audio))

    def _resultado(self) -> Acao | None:
        """O futuro que voltou: a transcrição (ou a resposta do detector) e o que ela decide."""
        futuro = self._futuro
        if futuro is None or not futuro.done():
            return None
        self._futuro = None
        try:
            valor = futuro.result()
        except Exception:  # ASR ou detector que falhou: não é fala com o Jarvis (na dúvida, não)
            valor = False if self._futuro_do_detector else ""
        if self._futuro_do_detector:
            self._futuro_do_detector = False
            if valor is True:
                return self._cortar(Motivo.ENDERECADA)
            return self._descartar(Motivo.NAO_ERA_COMIGO)
        return self._julgar(str(valor))

    def _julgar(self, texto: str) -> Acao | None:
        """A transcrição do trecho: corta, descarta, ou `None` = espera o trecho crescer."""
        palavras = _palavras(texto)
        if not palavras:
            self._sem_corte = Motivo.SEM_FALA
            return None
        eco = self._eco(palavras)
        achado = self.palavra.achar(texto)
        if achado is not None and not (eco and self._jarvis_disse_a_palavra()):
            return self._cortar(Motivo.PALAVRA_DE_ATIVACAO)
        if eco:
            self.portao.era_o_eco()
            return self._descartar(Motivo.ECO_DO_JARVIS)
        self._sem_corte = Motivo.SEM_CHAMADA
        if self.modo is not ModoDeEscuta.CONTINUA:
            return None  # na palavra, só a chamada corta
        if eh_ordem_de_parar(texto):
            return self._cortar(Motivo.ORDEM_DE_PARAR)
        if self.enderecada is not None and not self._trecho_contido:
            enderecada = self.enderecada
            self._futuro_do_detector = True
            self._futuro = self.enviar(lambda: enderecada(texto))
            return self._resultado()
        return None

    def _eco(self, palavras: list[str]) -> bool:
        uteis = [p for p in palavras if len(p) >= 2]
        if len(uteis) < 2 or not self._falado:
            return False
        falado = set(self._falado)
        return sum(p in falado for p in uteis) / len(uteis) >= SEMELHANCA_DE_ECO

    def _jarvis_disse_a_palavra(self) -> bool:
        return self.palavra.achar(" ".join(self._falado)) is not None

    def _cortar(self, motivo: Motivo) -> Acao:
        assert self._segmento is not None
        self._corte = bytes(self._segmento)
        self._registrar(Acao.CORTAR, motivo)
        self._fechar_segmento()
        return Acao.CORTAR

    def _descartar(self, motivo: Motivo) -> Acao:
        pausado = self._pausado
        self._registrar(Acao.RETOMAR if pausado else Acao.NADA, motivo)
        if self._silencio_ms < SILENCIO_PARA_FECHAR_MS:
            self._contida = True  # julgada no meio: o resto dela não pausa nem pergunta de novo
        self._fechar_segmento()
        return Acao.RETOMAR if pausado else Acao.NADA

    def _registrar(self, acao: Acao, motivo: Motivo) -> None:
        self.decisoes.append(Decisao(acao, motivo, self._ms_do_segmento))

    def _fechar_segmento(self) -> None:
        if self._futuro is not None:
            self._futuro.cancel()  # o que estava em voo não decide mais nada
        self._segmento = None
        self._futuro = None
        self._futuro_do_detector = False
        self._suspeito = self._pausado = False
        self._ms_do_segmento = self._fala_ms = self._silencio_ms = self._ms_da_pausa = 0.0
        self._fala_checada_ms = 0.0
        self._sem_corte = Motivo.SEM_FALA


__all__ = [
    "Acao",
    "Decisao",
    "Motivo",
    "PortaoDeEco",
    "VigiaDeInterrupcao",
    "eh_ordem_de_parar",
    "em_linha",
    "so_ordem_de_parar",
]
