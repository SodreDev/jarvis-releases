"""`jarvis --testar-chamada`: o dono prova, na máquina dele, a fonte virtual da ADR-0074 (fatia B).

O que mostra — só nomes de dispositivo e «ok/falhou», **nunca áudio** (nada é gravado em arquivo
nem tocado) e nenhum segredo:

1. o servidor de som (`pactl info`), a entrada e a saída padrão, e se a saída é fone (o que o
   modo «auto» do `fone` vai usar);
2. sobras de uma execução anterior (`jarvis_mix`/`jarvis_mic` já existindo) — com o comando para
   tirar à mão;
3. **liga** o misturador em modo sessão (nada no disco) e confere que a fonte virtual existe e
   virou a entrada padrão;
4. **o move**: abre uma captura de teste no microfone físico (um `parec` que descarta tudo) e
   confere que o Jarvis a moveu para a fonte virtual — é o que fará com o app de chamada;
5. **o mudo sem fone**: abafa e devolve o microfone real na mistura e confere;
6. **desliga** e confere que a entrada padrão voltou e que nada ficou carregado.

Recusa sob CI (o executor do sistema recusa). Testado só com executor falso; o resultado de
verdade é o que o dono manda de volta."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from jarvis.audio_io.ambiente import proibir_dispositivo_em_ci
from jarvis.audio_io.misturador import (
    NOME_DA_FONTE,
    NOME_DO_MIX,
    ErroDoMisturador,
    Executor,
    ExecutorDoSistema,
    Misturador,
    fone_na_saida,
)

ESPERA_DO_MOVE_S = 1.0


class CapturaDeTeste(Protocol):
    """Abre uma captura qualquer no microfone físico e diz o pid dela; `parar` fecha."""

    def iniciar(self, dispositivo: str) -> int: ...

    def parar(self) -> None: ...


@dataclass(slots=True)
class CapturaDeTesteParec:
    """Um `parec` no microfone físico com a saída jogada fora: nada é gravado."""

    _processo: subprocess.Popen[bytes] | None = None

    def iniciar(self, dispositivo: str) -> int:
        proibir_dispositivo_em_ci()
        programa = shutil.which("parec")
        if programa is None:
            raise FileNotFoundError("parec não está instalado (pacote pulseaudio-utils)")
        self._processo = subprocess.Popen(  # noqa: S603 — argv fixo, sem shell
            [programa, f"--device={dispositivo}", "--raw"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self._processo.pid

    def parar(self) -> None:
        if self._processo is not None:
            with contextlib.suppress(Exception):
                self._processo.terminate()
                self._processo.wait(timeout=2)
            self._processo = None


@dataclass(slots=True)
class Relatorio:
    escrever: Callable[[str], None]
    falhas: int = 0
    oks: int = 0
    linhas: list[str] = field(default_factory=list)

    def _linha(self, texto: str) -> None:
        self.linhas.append(texto)
        self.escrever(texto)

    def ok(self, texto: str) -> None:
        self.oks += 1
        self._linha(f"  ok      {texto}")

    def falhou(self, texto: str) -> None:
        self.falhas += 1
        self._linha(f"  FALHOU  {texto}")

    def info(self, texto: str) -> None:
        self._linha(f"  ·       {texto}")


def _pactl(executor: Executor, *argumentos: str) -> str:
    saida = executor.rodar(("pactl", *argumentos))
    if saida.codigo != 0:
        raise ErroDoMisturador(f"pactl {argumentos[0]}: {saida.texto.strip()[:160]}")
    return saida.texto.strip()


def _lista(executor: Executor, tipo: str) -> list[dict[str, Any]]:
    try:
        lido = json.loads(_pactl(executor, "-f", "json", "list", tipo) or "[]")
    except (ValueError, ErroDoMisturador):
        return []
    return [x for x in lido if isinstance(x, dict)] if isinstance(lido, list) else []


def _nomes_das_fontes(executor: Executor) -> dict[str, int]:
    return {
        str(f.get("name")): int(f["index"])
        for f in _lista(executor, "sources")
        if isinstance(f.get("index"), int)
    }


def testar_chamada(
    executor: Executor,
    escrever: Callable[[str], None],
    captura: CapturaDeTeste,
    *,
    esperar: Callable[[float], None] = time.sleep,
) -> int:
    """Roda os seis passos e devolve 0 (tudo ok) ou 1. Sempre desliga o que ligou."""
    r = Relatorio(escrever)
    escrever("Jarvis — teste da voz na ligação (ADR-0074). Nada é gravado nem tocado.")
    escrever("1. o som do sistema")
    try:
        info = _pactl(executor, "info")
    except ErroDoMisturador as erro:
        r.falhou(f"o pactl não respondeu ({erro}); instale pulseaudio-utils")
        escrever(f"resultado: {r.oks} ok, {r.falhas} falha(s)")
        return 1
    servidor = next(
        (linha.split(":", 1)[1].strip() for linha in info.splitlines() if "Server Name" in linha),
        "não informado",
    )
    r.ok(f"servidor de som: {servidor}")
    try:
        entrada_de_antes = _pactl(executor, "get-default-source")
        r.ok(f"entrada padrão: {entrada_de_antes}")
        r.ok(f"saída padrão: {_pactl(executor, 'get-default-sink')}")
    except ErroDoMisturador as erro:
        r.falhou(f"não li a entrada/saída padrão ({erro})")
        escrever(f"resultado: {r.oks} ok, {r.falhas} falha(s)")
        return 1
    fone = fone_na_saida(executor)
    r.info(
        "fone na saída: "
        + {True: "sim", False: "não", None: "o sistema não diz (o «auto» age como sem fone)"}[fone]
    )

    escrever("2. sobras de antes")
    fontes = _nomes_das_fontes(executor)
    if NOME_DA_FONTE in fontes or f"{NOME_DO_MIX}.monitor" in fontes:
        r.falhou(
            "a fonte virtual já existe (sobra de uma execução que caiu): veja `pactl list "
            "short modules | grep jarvis` e tire com `pactl unload-module <número>`"
        )
        escrever(f"resultado: {r.oks} ok, {r.falhas} falha(s)")
        return 1
    r.ok("nenhuma sobra")

    misturador = Misturador(executor=executor)
    try:
        escrever("3. ligar a fonte virtual (modo sessão, nada no disco)")
        try:
            misturador.ligar()
        except ErroDoMisturador as erro:
            r.falhou(f"não liguei ({erro})")
        else:
            _ligado(executor, r, escrever, misturador, captura, esperar)
    finally:
        with contextlib.suppress(Exception):
            captura.parar()
        escrever("6. desligar e conferir que voltou")
        misturador.desligar()
        try:
            depois = _pactl(executor, "get-default-source")
            if depois == entrada_de_antes:
                r.ok(f"a entrada padrão voltou: {depois}")
            else:
                r.falhou(f"a entrada padrão ficou {depois} (era {entrada_de_antes})")
        except ErroDoMisturador as erro:
            r.falhou(f"não li a entrada padrão no fim ({erro})")
        if NOME_DA_FONTE in _nomes_das_fontes(executor):
            r.falhou("a fonte virtual continuou carregada")
        else:
            r.ok("nada ficou carregado")
    return _fim(r, escrever)


def _ligado(
    executor: Executor,
    r: Relatorio,
    escrever: Callable[[str], None],
    misturador: Misturador,
    captura: CapturaDeTeste,
    esperar: Callable[[float], None],
) -> None:
    """Os passos 3 a 5, com a fonte virtual ligada."""
    fontes = _nomes_das_fontes(executor)
    if NOME_DA_FONTE in fontes:
        r.ok(f"fonte virtual criada: {NOME_DA_FONTE}")
    else:
        r.falhou("a fonte virtual não apareceu na lista do servidor")
    padrao = _pactl(executor, "get-default-source")
    if padrao == NOME_DA_FONTE:
        r.ok("a fonte virtual virou a entrada padrão")
    else:
        r.falhou(f"a entrada padrão continua {padrao}")

    escrever("4. mover uma captura do microfone físico para a fonte virtual")
    try:
        pid = captura.iniciar(misturador.fisico)
    except Exception as erro:
        r.falhou(f"não abri a captura de teste ({type(erro).__name__}: {erro})")
        pid = None
    if pid is not None:
        esperar(ESPERA_DO_MOVE_S)
        misturador.mover()
        alvo = _nomes_das_fontes(executor).get(NOME_DA_FONTE)
        da_captura = [
            f
            for f in _lista(executor, "source-outputs")
            if str((f.get("properties") or {}).get("application.process.id", "")) == str(pid)
        ]
        if not da_captura:
            r.falhou("a captura de teste não apareceu no servidor")
        elif all(f.get("source") == alvo for f in da_captura):
            r.ok("a captura foi movida para a fonte virtual")
        else:
            r.falhou("a captura continua no microfone físico (o move não pegou)")
        for aviso in misturador.avisos:
            r.info(aviso)
        captura.parar()

    escrever("5. abafar o microfone real na mistura (o modo sem fone)")
    misturador.abafar(True)
    mudo = _mudo_do_loopback(executor, misturador)
    misturador.abafar(False)
    voltou = _mudo_do_loopback(executor, misturador)
    if mudo is True and voltou is False:
        r.ok("abafou e devolveu")
    elif mudo is None:
        r.info("o servidor não informou o mudo; confira de ouvido numa chamada de teste")
    else:
        r.falhou("o mudo não mudou como esperado")


def _mudo_do_loopback(executor: Executor, misturador: Misturador) -> bool | None:
    for fluxo in _lista(executor, "sink-inputs"):
        if str(fluxo.get("owner_module", "")) == misturador._loopback and "mute" in fluxo:
            return bool(fluxo["mute"])
    return None


def _fim(r: Relatorio, escrever: Callable[[str], None]) -> int:
    escrever(f"resultado: {r.oks} ok, {r.falhas} falha(s)")
    return 0 if r.falhas == 0 else 1


def testar_chamada_no_sistema(escrever: Callable[[str], None] = print) -> int:
    """O que `jarvis --testar-chamada` roda: o executor e a captura de verdade."""
    proibir_dispositivo_em_ci()
    return testar_chamada(ExecutorDoSistema(), escrever, CapturaDeTesteParec())


__all__ = ["CapturaDeTesteParec", "testar_chamada", "testar_chamada_no_sistema"]
