"""A lista de modelos de cada provedor: ao vivo, guardada ou a do registro (ADR-0056).

Pedido do dono (2026-10-29): ver **todos** os modelos que o provedor oferece, não um por tipo. A
lista muda mais depressa que qualquer arquivo do repositório (modelo novo, modelo aposentado),
então ela vem do próprio provedor — e, para a tela não depender da rede a cada abertura, fica
guardada:

1. **guardada e fresca** (menos de `VALIDADE_S`): vale a guardada, sem rede;
2. senão, **ao vivo** (`ProvedorDeModelos.listar`), e o resultado é guardado;
3. a ao vivo falhou (sem chave, sem rede, sem o comando): vale a **guardada**, de qualquer idade,
   com o aviso de quando ela é;
4. nem isso: vale a **do registro** (`modelos`, conferida na página oficial, com data).

O que vem do provedor passa pela forma (`interface.FORMA_DO_ID`, `limpar_texto`) na ida e na
volta do disco: o arquivo do cache é dado como qualquer outro, e pode ter sido mexido. Ele não
guarda segredo — a chave só existe no cabeçalho do pedido — nem nada do dono.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.provedores.interface import (
    MAXIMO_DE_MODELOS,
    Capacidades,
    ListagemIndisponivel,
    Modelo,
    ProvedorDeModelos,
    id_valido,
    limpar_texto,
)
from jarvis.provedores.registro import (
    RegraDeCapacidade,
    capacidades_do_registro,
    modelos_estaticos,
)
from jarvis.voz.interface import Cancelado, nunca_cancelado
from jarvis.voz.registro import Motor

VALIDADE_S: Final = 24 * 3600.0
"""Um dia: a lista de um provedor não muda de hora em hora, e o dono pode pedir a de agora."""
VERSAO: Final = 1


class Origem(StrEnum):
    PROVEDOR = "provedor"
    """Lida agora, do endpoint ou do comando oficial do provedor."""
    CACHE = "cache"
    """Lida antes e guardada no disco."""
    REGISTRO = "registro"
    """A lista estática do registro, conferida à mão na página oficial."""


@dataclass(frozen=True, slots=True)
class Listagem:
    """Os modelos de um provedor e de onde a lista veio."""

    provedor: str
    modelos: tuple[Modelo, ...]
    origem: Origem
    lida_em: str
    """Quando a lista foi lida (ISO 8601, UTC) — no registro, a data da conferência."""
    aviso: str = ""
    """Por que não é a lista de agora, quando não é."""

    def modelo(self, identificador: str) -> Modelo | None:
        return next((m for m in self.modelos if m.id == identificador), None)

    def para_dict(self) -> dict[str, Any]:
        return {
            "provedor": self.provedor,
            "origem": self.origem.value,
            "lidaEm": self.lida_em,
            "aviso": self.aviso,
            "modelos": [m.para_dict() for m in self.modelos],
        }


def pasta_do_cache(ambiente: Mapping[str, str] | None = None) -> Path | None:
    """`$XDG_CACHE_HOME/jarvis/modelos` (ou `~/.cache/...`, `%LOCALAPPDATA%\\jarvis\\...`). Um
    ambiente **explícito** sem nenhuma dessas (o da suíte) não tem cache: cair na casa do processo
    seria escrever na pasta do dono num teste."""
    fonte = ambiente_ou_os(ambiente)
    if os.name == "nt":  # pragma: no cover — caminho do Windows, sem CI aqui
        base = fonte.get("LOCALAPPDATA") or ""
        if not base and ambiente is None:
            base = str(Path.home() / "AppData" / "Local")
    else:
        base = fonte.get("XDG_CACHE_HOME") or ""
        if not base and fonte.get("HOME"):
            base = str(Path(fonte["HOME"]) / ".cache")
        if not base and ambiente is None:
            base = str(Path.home() / ".cache")
    return Path(base) / "jarvis" / "modelos" if base else None


def _agora_iso(segundos: float) -> str:
    return datetime.fromtimestamp(segundos, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _segundos(iso: str) -> float | None:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _modelos_de(bruto: object) -> tuple[Modelo, ...]:
    """Os modelos de uma lista de terceiros (resposta ou cache): só os que têm forma."""
    if not isinstance(bruto, list):
        return ()
    vistos: dict[str, Modelo] = {}
    for item in bruto[:MAXIMO_DE_MODELOS]:
        if not isinstance(item, Mapping):
            continue
        identificador = id_valido(item.get("id"))
        if identificador and identificador not in vistos:
            vistos[identificador] = Modelo(
                id=identificador,
                nome=limpar_texto(item.get("nome")),
                capacidades=Capacidades.de_dict(item.get("capacidades")),
            )
    return tuple(vistos.values())


@dataclass(slots=True)
class Catalogo:
    """Onde a lista de cada provedor fica guardada, e a regra de qual lista vale."""

    pasta: Path | None
    validade_s: float = VALIDADE_S
    relogio: Callable[[], float] = field(default=time.time)

    def listar(
        self,
        provedor: ProvedorDeModelos,
        registro: Motor,
        regras: tuple[RegraDeCapacidade, ...] = (),
        *,
        forcar: bool = False,
        cancelado: Cancelado = nunca_cancelado,
    ) -> Listagem:
        """A lista que vale agora, pela ordem do cabeçalho. `forcar` pula a guardada fresca (o
        botão "buscar de novo" da tela)."""
        guardada = self.guardada(registro, regras)
        if guardada is not None and not forcar and self._fresca(guardada):
            return guardada
        try:
            vivos = provedor.listar(cancelado=cancelado)
        except ListagemIndisponivel as erro:
            if guardada is not None:
                return replace(
                    guardada,
                    aviso=f"a lista de agora não veio ({erro}); vale a guardada de "
                    f"{guardada.lida_em}",
                )
            return self.do_registro(
                registro,
                regras,
                aviso=f"a lista de agora não veio ({erro}); vale a do registro, conferida em "
                f"{registro.data_dos_modelos or '?'}",
            )
        lida_em = _agora_iso(self.relogio())
        self._guardar(registro.id, vivos, lida_em)
        return Listagem(
            registro.id, _completar(registro.id, vivos, regras), Origem.PROVEDOR, lida_em
        )

    def sem_rede(self, registro: Motor, regras: tuple[RegraDeCapacidade, ...] = ()) -> Listagem:
        """A melhor lista **sem abrir socket**: a guardada (de qualquer idade), senão a do
        registro. É a que confere o modelo na hora de chamar e a que a tela mostra ao abrir."""
        return self.guardada(registro, regras) or self.do_registro(registro, regras)

    def do_registro(
        self, registro: Motor, regras: tuple[RegraDeCapacidade, ...] = (), *, aviso: str = ""
    ) -> Listagem:
        return Listagem(
            registro.id,
            modelos_estaticos(registro, regras),
            Origem.REGISTRO,
            registro.data_dos_modelos or registro.data_de_acesso,
            aviso,
        )

    def guardada(
        self, registro: Motor, regras: tuple[RegraDeCapacidade, ...] = ()
    ) -> Listagem | None:
        arquivo = self._arquivo(registro.id)
        if arquivo is None or not arquivo.is_file():
            return None
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not isinstance(dados, Mapping) or dados.get("versao") != VERSAO:
            return None
        lida_em = dados.get("lida_em")
        modelos = _modelos_de(dados.get("modelos"))
        if not isinstance(lida_em, str) or _segundos(lida_em) is None or not modelos:
            return None
        return Listagem(
            registro.id, _completar(registro.id, modelos, regras), Origem.CACHE, lida_em
        )

    def _fresca(self, listagem: Listagem) -> bool:
        lida = _segundos(listagem.lida_em)
        return lida is not None and 0 <= self.relogio() - lida < self.validade_s

    def _arquivo(self, identificador: str) -> Path | None:
        return self.pasta / f"{identificador}.json" if self.pasta is not None else None

    def _guardar(self, identificador: str, modelos: tuple[Modelo, ...], lida_em: str) -> None:
        """Grava a lista como o provedor a deu (o registro completa na leitura). Falha de disco
        não derruba a listagem: o cache é conveniência."""
        arquivo = self._arquivo(identificador)
        if arquivo is None or not modelos:
            return
        corpo = {
            "versao": VERSAO,
            "provedor": identificador,
            "lida_em": lida_em,
            "modelos": [m.para_dict() for m in modelos[:MAXIMO_DE_MODELOS]],
        }
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            temporario = arquivo.with_suffix(".json.tmp")
            temporario.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
            temporario.replace(arquivo)
        except OSError:
            return


def _completar(
    provedor: str, modelos: tuple[Modelo, ...], regras: tuple[RegraDeCapacidade, ...]
) -> tuple[Modelo, ...]:
    """O que o provedor disse, com o que ele não disse preenchido pelo registro."""
    return tuple(
        m.com_capacidades(m.capacidades.completar(capacidades_do_registro(provedor, m.id, regras)))
        for m in modelos
    )


def modelos_da_resposta(itens: object) -> tuple[Modelo, ...]:
    """Para os provedores: a lista já convertida (dicts com `id`, `nome`, `capacidades`) passa
    pela mesma forma do cache."""
    return _modelos_de(itens)


__all__ = [
    "VALIDADE_S",
    "Catalogo",
    "Listagem",
    "Origem",
    "modelos_da_resposta",
    "pasta_do_cache",
]
