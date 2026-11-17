"""O outro lado da ligação, sozinho: só o fluxo do app de chamada (ADR-0074, fatia B).

O estudo (`docs/estudos/voz-na-ligacao.md` §2.1) pede o áudio de **quem liga** sem o resto da
saída do PC (música, vídeo, os avisos do sistema). Em modo sessão, com `pactl` atrás do mesmo
`Executor` do misturador:

1. um sink nulo `jarvis_outro_lado` e um loopback do monitor dele para a **saída de antes** do
   fluxo — o dono continua ouvindo quem liga onde ouvia;
2. o fluxo do app de chamada (o `sink-input` escolhido por `escolher`, ex.: `por_app("chromium")`)
   é **movido** para o sink nulo;
3. o ASR grava de `jarvis_outro_lado.monitor` (`FONTE_DO_OUTRO_LADO`): só quem liga.

`desligar` devolve o fluxo à saída de antes e descarrega os módulos, na ordem inversa; falha no
meio de `ligar` desfaz o que criou. Mais de um fluxo que casa (duas abas tocando): escolhe o mais
recente e avisa — o dono pode fechar a outra. Nada aqui toca áudio nos testes (executor falso); o
`ExecutorDoSistema` recusa sob CI. **Não provado na máquina real:** se o navegador do dono expõe a
chamada como um `sink-input` separado (o Chromium costuma pôr cada aba que toca num fluxo) e se o
move não é revertido por ele."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.audio_io.misturador import ErroDoMisturador, Executor

NOME_DO_SINK: Final = "jarvis_outro_lado"
FONTE_DO_OUTRO_LADO: Final = f"{NOME_DO_SINK}.monitor"
LATENCIA_MS: Final = 20


def por_app(*nomes: str) -> Callable[[Mapping[str, Any]], bool]:
    """Casa o fluxo pelo binário ou pelo nome do app (sem diferença de caixa)."""
    alvos = {n.casefold() for n in nomes if n}

    def casa(propriedades: Mapping[str, Any]) -> bool:
        binario = str(propriedades.get("application.process.binary", "")).casefold()
        nome = str(propriedades.get("application.name", "")).casefold()
        return binario in alvos or nome in alvos

    return casa


def _propriedades(fluxo: Mapping[str, Any]) -> Mapping[str, Any]:
    props = fluxo.get("properties")
    return props if isinstance(props, Mapping) else {}


@dataclass(slots=True)
class CapturaDoOutroLado:
    executor: Executor
    ligado: bool = False
    fluxo: int | None = None
    _saida_de_antes: str = ""
    _modulos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def _pactl(self, *argumentos: str) -> str:
        saida = self.executor.rodar(("pactl", *argumentos))
        if saida.codigo != 0:
            raise ErroDoMisturador(f"pactl {argumentos[0]} falhou: {saida.texto.strip()[:200]}")
        return saida.texto.strip()

    def _lista(self, tipo: str) -> list[dict[str, Any]]:
        import json

        try:
            lido = json.loads(self._pactl("-f", "json", "list", tipo) or "[]")
        except ValueError as erro:
            raise ErroDoMisturador(f"pactl list {tipo}: JSON inválido") from erro
        return [x for x in lido if isinstance(x, dict)] if isinstance(lido, list) else []

    def _nome_do_sink(self, indice: object) -> str:
        for sink in self._lista("sinks"):
            if sink.get("index") == indice:
                return str(sink.get("name", ""))
        return ""

    def ligar(self, escolher: Callable[[Mapping[str, Any]], bool]) -> str:
        """Isola o fluxo do app de chamada e devolve a fonte a gravar. Sem fluxo que case,
        `ErroDoMisturador` (nada é criado)."""
        if self.ligado:
            return FONTE_DO_OUTRO_LADO
        candidatos = [
            f
            for f in self._lista("sink-inputs")
            if isinstance(f.get("index"), int) and escolher(_propriedades(f))
        ]
        if not candidatos:
            raise ErroDoMisturador("nenhum fluxo do app de chamada tocando agora")
        if len(candidatos) > 1:
            self.avisos.append(f"{len(candidatos)} fluxos do app tocando: usei o mais recente")
        escolhido = max(candidatos, key=lambda f: int(f["index"]))
        try:
            self._saida_de_antes = self._nome_do_sink(escolhido.get("sink"))
            if not self._saida_de_antes:
                raise ErroDoMisturador("não sei em que saída o fluxo tocava")
            self._carregar(
                "module-null-sink",
                f"sink_name={NOME_DO_SINK}",
                "sink_properties=device.description=Jarvis-outro-lado",
            )
            self._carregar(
                "module-loopback",
                f"source={FONTE_DO_OUTRO_LADO}",
                f"sink={self._saida_de_antes}",
                f"latency_msec={LATENCIA_MS}",
                "source_dont_move=true",
            )
            self._pactl("move-sink-input", str(escolhido["index"]), NOME_DO_SINK)
            self.fluxo = int(escolhido["index"])
            self.ligado = True
        except Exception:
            self.desligar()
            raise
        return FONTE_DO_OUTRO_LADO

    def _carregar(self, modulo: str, *argumentos: str) -> None:
        indice = self._pactl("load-module", modulo, *argumentos)
        if not indice.isdigit():
            raise ErroDoMisturador(f"{modulo}: o servidor não devolveu o índice")
        self._modulos.append(indice)

    def desligar(self) -> None:
        """Devolve o fluxo à saída de antes e descarrega o que criou. Tolerante ao que sumiu."""
        if self.fluxo is not None and self._saida_de_antes:
            with contextlib.suppress(Exception):
                self.executor.rodar(
                    ("pactl", "move-sink-input", str(self.fluxo), self._saida_de_antes)
                )
        for modulo in reversed(self._modulos):
            with contextlib.suppress(Exception):
                self.executor.rodar(("pactl", "unload-module", modulo))
        self._modulos.clear()
        self.fluxo = None
        self.ligado = False


__all__ = ["FONTE_DO_OUTRO_LADO", "NOME_DO_SINK", "CapturaDoOutroLado", "por_app"]
