"""Timers, alarmes e lembretes que viram `Notification` (ADR-0025; dono, 2026-10-18).

"Me lembra em 10 minutos de tirar o bolo": o Jarvis agenda e **esquece** — quem lembra é este
agendador, numa linha própria, que acorda no instante certo e entrega o lembrete à fila de avisos
(o Jarvis decide como dizê-lo, sem cortar fala em andamento). Persiste em arquivo na área do
Jarvis, então sobrevive a fechar e abrir; o que venceu enquanto estava fechado dispara **ao abrir**,
marcado como atrasado — lembrete perdido calado é pior do que atrasado.

A mensagem é texto que o modelo escreveu a partir do que o dono pediu: é **dita**, nunca executada,
e vai curta (200 caracteres).
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from jarvis.barramento.envelope import uuid7

LIMITE_DE_ALARMES: Final = 50
MAXIMO_DE_SEGUNDOS: Final = 30 * 86400
LIMITE_DA_MENSAGEM: Final = 200


@dataclass(frozen=True, slots=True)
class Alarme:
    id: str
    mensagem: str
    quando: float
    """Instante em segundos da época (relógio de parede), não `monotonic`: sobrevive a reiniciar."""
    atrasado: bool = False

    def em_segundos(self, agora: float) -> int:
        return max(0, round(self.quando - agora))


def quando_da_fala(*, em_segundos: int | None, as_: str | None, agora: datetime) -> float:
    """Resolve "daqui a N segundos" ou "às HH:MM / data-hora ISO" para um instante da época."""
    if (em_segundos is None) == (as_ is None):
        raise ValueError("diga `em_segundos` ou `as` (hora ou data e hora), um dos dois")
    if em_segundos is not None:
        if not 1 <= em_segundos <= MAXIMO_DE_SEGUNDOS:
            raise ValueError(f"`em_segundos` vai de 1 a {MAXIMO_DE_SEGUNDOS} (30 dias)")
        return agora.timestamp() + em_segundos
    texto = str(as_).strip()
    try:
        alvo = datetime.fromisoformat(texto)
    except ValueError:
        try:
            hora = datetime.strptime(texto, "%H:%M").time()
        except ValueError:
            raise ValueError("`as` é HH:MM ou data e hora ISO (2026-10-20T14:30)") from None
        alvo = agora.replace(hour=hora.hour, minute=hora.minute, second=0, microsecond=0)
        if alvo <= agora:
            alvo += timedelta(days=1)  # "às 7" dito de noite é amanhã
    if alvo.tzinfo is None:
        alvo = alvo.astimezone()
    alvo_epoca = alvo.timestamp()
    if alvo_epoca <= agora.timestamp():
        raise ValueError("esse horário já passou")
    if alvo_epoca - agora.timestamp() > MAXIMO_DE_SEGUNDOS:
        raise ValueError("passa de 30 dias: é longe demais para um lembrete")
    return alvo_epoca


@dataclass(slots=True)
class AgendaDeAlarmes:
    arquivo: Path
    ao_disparar: Callable[[Alarme], None]
    """Quem recebe o lembrete (o laço o põe na fila de avisos). Chamada da linha da agenda."""
    relogio: Callable[[], float] = time.time
    alarmes: dict[str, Alarme] = field(default_factory=dict)
    _condicao: threading.Condition = field(default_factory=threading.Condition, repr=False)
    _linha: threading.Thread | None = field(default=None, repr=False)
    _parar: bool = False

    # --- o que as tools pedem ---------------------------------------------------------------
    def agendar(self, mensagem: str, quando: float) -> Alarme:
        mensagem = " ".join(mensagem.split())[:LIMITE_DA_MENSAGEM]
        with self._condicao:
            if len(self.alarmes) >= LIMITE_DE_ALARMES:
                raise ValueError(f"já há {LIMITE_DE_ALARMES} alarmes: cancele algum")
            alarme = Alarme(f"al-{uuid7()[-8:]}", mensagem, quando)
            self.alarmes[alarme.id] = alarme
            self._gravar()
            self._condicao.notify_all()
        return alarme

    def cancelar(self, alarme_id: str) -> Alarme:
        with self._condicao:
            alarme = self.alarmes.pop(alarme_id, None)
            if alarme is None:
                raise ValueError(f"não existe o alarme {alarme_id!r}")
            self._gravar()
            self._condicao.notify_all()
        return alarme

    def listar(self) -> list[Alarme]:
        with self._condicao:
            return sorted(self.alarmes.values(), key=lambda a: a.quando)

    # --- a linha ---------------------------------------------------------------------------
    def iniciar(self) -> None:
        """Lê o arquivo (o que venceu fechado dispara agora, atrasado) e começa a esperar."""
        with self._condicao:
            self._ler()
            self._parar = False
        self._linha = threading.Thread(target=self._correr, name="jarvis-alarmes", daemon=True)
        self._linha.start()

    def encerrar(self) -> None:
        with self._condicao:
            self._parar = True
            self._condicao.notify_all()
        if self._linha is not None:
            self._linha.join(timeout=2.0)

    def _correr(self) -> None:
        while True:
            vencidos: list[Alarme] = []
            with self._condicao:
                if self._parar:
                    return
                agora = self.relogio()
                vencidos = [a for a in self.alarmes.values() if a.quando <= agora]
                for a in vencidos:
                    del self.alarmes[a.id]
                if vencidos:
                    self._gravar()
                else:
                    proximo = min((a.quando for a in self.alarmes.values()), default=None)
                    espera = None if proximo is None else max(0.01, min(proximo - agora, 30.0))
                    self._condicao.wait(timeout=espera)
            for alarme in sorted(vencidos, key=lambda a: a.quando):
                with contextlib.suppress(Exception):  # entrega que falha não derruba a agenda
                    self.ao_disparar(alarme)

    # --- arquivo ---------------------------------------------------------------------------
    def _gravar(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        corpo = [asdict(a) for a in self.alarmes.values()]
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
        temporario.replace(self.arquivo)

    def _ler(self) -> None:
        try:
            bruto = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        agora = self.relogio()
        for item in bruto if isinstance(bruto, list) else []:
            try:
                alarme = Alarme(
                    str(item["id"]),
                    str(item["mensagem"])[:LIMITE_DA_MENSAGEM],
                    float(item["quando"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if alarme.quando < agora - 1:
                alarme = Alarme(alarme.id, alarme.mensagem, alarme.quando, atrasado=True)
            self.alarmes[alarme.id] = alarme


_AGENDAS: dict[Path, AgendaDeAlarmes] = {}
_TRAVA_DAS_AGENDAS = threading.Lock()


def agenda_compartilhada(arquivo: Path, ao_disparar: Callable[[Alarme], None]) -> AgendaDeAlarmes:
    """A agenda **deste arquivo**, uma só por processo, que sobrevive às conversas.

    Cada vez que o dono começa uma conversa nasce um laço novo; se cada um tivesse a sua agenda, o
    lembrete morreria com o "encerrar" e o arquivo seria lido duas vezes. Então a agenda é única e
    só **troca quem recebe** o aviso: o laço mais novo.
    """
    with _TRAVA_DAS_AGENDAS:
        agenda = _AGENDAS.get(arquivo)
        if agenda is None:
            agenda = AgendaDeAlarmes(arquivo, ao_disparar)
            _AGENDAS[arquivo] = agenda
            agenda.iniciar()
        else:
            agenda.ao_disparar = ao_disparar
        return agenda
