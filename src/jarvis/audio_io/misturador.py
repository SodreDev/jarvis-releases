"""A fonte virtual que assume o lugar do microfone, como o Soundpad (ADR-0074, fatia 1).

O estudo (`docs/estudos/voz-na-ligacao.md` §1) descreve três camadas; aqui moram as duas que dá
para provar com um executor falso, e a geração dos arquivos da terceira:

- **modo sessão** (`Misturador`): só comandos `pactl` em tempo de execução, nada no disco.
  `ligar` cria um sink nulo `jarvis_mix`, um loopback do microfone físico para ele (onde a voz do
  Jarvis também toca) e uma fonte remapeada `jarvis_mic` sobre o monitor dele — a forma «sink nulo
  + monitor remapeado» do §1.1, que o Chromium lista como microfone (ele esconde fontes
  «monitor»). Depois (a) `jarvis_mic` vira a entrada padrão (conferida lendo de volta) e (b) toda
  captura de app que está no físico — menos o próprio Jarvis e o loopback — é movida para ela,
  com teto de re-movimento para app que reverte. `desligar` devolve cada fluxo, o padrão e
  descarrega os módulos, na ordem inversa; falha no meio do `ligar` desfaz o que já criou. **Não
  verificado:** se os módulos carregados pelo `pactl` sobrevivem ao Jarvis cair (no PulseAudio
  ficam até o servidor reiniciar) — por isso `desligar` roda no encerramento normal e o guia diz
  como descarregar à mão (`pactl unload-module`); confirmar na máquina do dono;
- **modo instalado** (`config_pipewire`, `config_wireplumber`, `Instalacao`): gera os dois arquivos
  de `~/.config` em que a fonte virtual assume o nome e a descrição do físico, e o físico é
  renomeado. Grava só com `confirmado=True` (o dono viu o conteúdo), guarda cópia do que
  substituir e desfaz restaurando a cópia. Reiniciar os serviços passa pelo executor.

**Nada aqui toca o áudio real nos testes**: o executor é uma interface. O do sistema
(`ExecutorDoSistema`) recusa rodar sob `CI=1` (`proibir_dispositivo_em_ci`), e as pastas de
configuração são parâmetros. O que só a máquina do dono prova (se o PipeWire/WirePlumber dele
aceita a fonte como padrão e o move, Discord/navegador reais, latência, eco, o nome trocado) está
no §5 do estudo.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from jarvis.audio_io.ambiente import proibir_dispositivo_em_ci

NOME_DO_MIX: Final = "jarvis_mix"
NOME_DA_FONTE: Final = "jarvis_mic"
DESCRICAO_DA_FONTE: Final = "Microfone (com a voz do Jarvis)"
LATENCIA_MS: Final = 5
TETO_DE_MOVIMENTOS: Final = 3
"""Quantas vezes o mesmo fluxo é movido de novo se o app o devolver ao físico."""
ARQUIVO_DE_CONFIGURACAO: Final = "50-jarvis-microfone.conf"
SUFIXO_DO_FISICO: Final = ".jarvis-direto"


class ErroDoMisturador(RuntimeError):
    """Um comando falhou; a mensagem diz qual (sem caminho do usuário)."""


@dataclass(frozen=True, slots=True)
class Saida:
    codigo: int
    texto: str = ""


class Executor(Protocol):
    """Quem roda os comandos. Nos testes, um falso que responde do roteiro."""

    def rodar(self, argv: Sequence[str]) -> Saida: ...


@dataclass(slots=True)
class ExecutorDoSistema:
    """Roda de verdade (sem shell). Recusa sob CI: a suíte nunca mexe no áudio do dono."""

    prazo_s: float = 10.0

    def rodar(self, argv: Sequence[str]) -> Saida:
        proibir_dispositivo_em_ci()
        programa = shutil.which(argv[0])
        if programa is None:
            return Saida(127, f"{argv[0]} não está instalado")
        feito = subprocess.run(  # noqa: S603 — argv fixo deste módulo, sem shell
            [programa, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=self.prazo_s,
            check=False,
        )
        return Saida(feito.returncode, feito.stdout if feito.returncode == 0 else feito.stderr)


# --- modo sessão ---------------------------------------------------------------------------
@dataclass(slots=True)
class Misturador:
    executor: Executor
    pid_do_jarvis: int = field(default_factory=os.getpid)
    ligado: bool = False
    fisico: str = ""
    _modulos: list[str] = field(default_factory=list)
    _padrao_anterior: str = ""
    _movidos: dict[int, str] = field(default_factory=dict)
    """índice do fluxo → nome da fonte em que ele estava."""
    _movimentos: dict[int, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    """O que não deu certo sem ser fatal (padrão não aceito, app que reverte além do teto)."""

    def _pactl(self, *argumentos: str) -> str:
        saida = self.executor.rodar(("pactl", *argumentos))
        if saida.codigo != 0:
            raise ErroDoMisturador(f"pactl {argumentos[0]} falhou: {saida.texto.strip()[:200]}")
        return saida.texto.strip()

    def _json(self, *argumentos: str) -> list[dict[str, Any]]:
        bruto = self._pactl("-f", "json", *argumentos)
        try:
            lido = json.loads(bruto or "[]")
        except ValueError as erro:
            raise ErroDoMisturador(f"pactl {' '.join(argumentos)}: JSON inválido") from erro
        return [item for item in lido if isinstance(item, dict)] if isinstance(lido, list) else []

    def ligar(self, fisico: str = "") -> None:
        """Cria a fonte virtual, faz dela o padrão e move para ela as capturas do físico."""
        if self.ligado:
            return
        try:
            self._padrao_anterior = self._pactl("get-default-source")
            self.fisico = fisico or self._padrao_anterior
            if not self.fisico or self.fisico == NOME_DA_FONTE:
                raise ErroDoMisturador("não sei qual é o microfone físico")
            self._carregar(
                "module-null-sink",
                f"sink_name={NOME_DO_MIX}",
                "sink_properties=device.description=Jarvis-mistura",
            )
            self._carregar(
                "module-loopback",
                f"source={self.fisico}",
                f"sink={NOME_DO_MIX}",
                f"latency_msec={LATENCIA_MS}",
                "source_dont_move=true",
                "sink_dont_move=true",
            )
            self._carregar(
                "module-remap-source",
                f"master={NOME_DO_MIX}.monitor",
                f"source_name={NOME_DA_FONTE}",
                f"source_properties=device.description={DESCRICAO_DA_FONTE.replace(' ', '-')}",
            )
            self._pactl("set-default-source", NOME_DA_FONTE)
            if self._pactl("get-default-source") != NOME_DA_FONTE:
                self.avisos.append("o servidor não aceitou a fonte virtual como padrão")
            self.ligado = True
            self.mover()
        except Exception:
            self.desligar()
            raise

    def _carregar(self, modulo: str, *argumentos: str) -> None:
        indice = self._pactl("load-module", modulo, *argumentos)
        if not indice.isdigit():
            raise ErroDoMisturador(f"{modulo}: o servidor não devolveu o índice")
        self._modulos.append(indice)

    def _indice_da_fonte(self, nome: str) -> int | None:
        for fonte in self._json("list", "sources"):
            if fonte.get("name") == nome and isinstance(fonte.get("index"), int):
                return int(fonte["index"])
        return None

    def mover(self) -> int:
        """Move para a fonte virtual as capturas que estão no físico. Devolve quantas moveu.

        Chamado ao ligar e a cada mudança do grafo (o observador do app). Não move o próprio
        Jarvis (ele ouve o microfone REAL) nem o loopback que alimenta a mistura."""
        if not self.ligado:
            return 0
        fisico = self._indice_da_fonte(self.fisico)
        if fisico is None:
            return 0
        movidos = 0
        for fluxo in self._json("list", "source-outputs"):
            indice = fluxo.get("index")
            if not isinstance(indice, int) or fluxo.get("source") != fisico:
                continue
            props = fluxo.get("properties") or {}
            if not isinstance(props, Mapping):
                props = {}
            if str(props.get("application.process.id", "")) == str(self.pid_do_jarvis):
                continue
            if str(fluxo.get("owner_module", "")) in self._modulos:
                continue
            vezes = self._movimentos.get(indice, 0)
            if vezes >= TETO_DE_MOVIMENTOS:
                aviso = f"o fluxo {indice} volta sozinho ao microfone físico"
                if aviso not in self.avisos:
                    self.avisos.append(aviso)
                continue
            self._pactl("move-source-output", str(indice), NOME_DA_FONTE)
            self._movidos.setdefault(indice, self.fisico)
            self._movimentos[indice] = vezes + 1
            movidos += 1
        return movidos

    def desligar(self) -> None:
        """Devolve tudo como estava. Tolerante: o que já sumiu não impede o resto."""
        existentes: set[int] = set()
        with contextlib.suppress(ErroDoMisturador):
            existentes = {
                int(f["index"])
                for f in self._json("list", "source-outputs")
                if isinstance(f.get("index"), int)
            }
        for indice, origem in list(self._movidos.items()):
            if indice in existentes:
                self.executor.rodar(("pactl", "move-source-output", str(indice), origem))
        self._movidos.clear()
        self._movimentos.clear()
        if self._padrao_anterior and self._padrao_anterior != NOME_DA_FONTE:
            self.executor.rodar(("pactl", "set-default-source", self._padrao_anterior))
        for modulo in reversed(self._modulos):
            self.executor.rodar(("pactl", "unload-module", modulo))
        self._modulos.clear()
        self.ligado = False


# --- modo instalado ------------------------------------------------------------------------
def _spa(valor: str) -> str:
    """Uma string SPA-JSON entre aspas (o formato dos .conf do PipeWire)."""
    return json.dumps(valor, ensure_ascii=False)


def config_pipewire(nome_do_fisico: str, descricao_do_fisico: str) -> str:
    """`~/.config/pipewire/pipewire.conf.d/50-jarvis-microfone.conf`: o sink de mistura, o
    loopback do físico (renomeado) para ele, e a fonte com o NOME e a DESCRIÇÃO originais do
    físico. Existe mesmo com o Jarvis fechado: o microfone continua funcionando."""
    renomeado = nome_do_fisico + SUFIXO_DO_FISICO
    return f"""# Gerado pelo Jarvis (ADR-0074, modo instalado). Apague este arquivo para desfazer.
context.objects = [
    {{ factory = adapter
        args = {{
            factory.name = support.null-audio-sink
            node.name = {_spa(NOME_DO_MIX)}
            node.description = "Jarvis — mistura"
            media.class = Audio/Sink
            audio.position = [ MONO ]
        }}
    }}
]
context.modules = [
    {{ name = libpipewire-module-loopback
        args = {{
            node.description = "Jarvis — microfone na mistura"
            capture.props = {{
                node.name = "jarvis.captura-do-microfone"
                target.object = {_spa(renomeado)}
                node.passive = true
                audio.position = [ MONO ]
            }}
            playback.props = {{
                node.name = "jarvis.microfone-na-mistura"
                target.object = {_spa(NOME_DO_MIX)}
                node.dont-reconnect = true
                audio.position = [ MONO ]
            }}
        }}
    }}
    {{ name = libpipewire-module-loopback
        args = {{
            node.description = {_spa(descricao_do_fisico)}
            capture.props = {{
                node.name = "jarvis.saida-da-mistura"
                stream.capture.sink = true
                target.object = {_spa(NOME_DO_MIX)}
                node.passive = true
                audio.position = [ MONO ]
            }}
            playback.props = {{
                node.name = {_spa(nome_do_fisico)}
                node.description = {_spa(descricao_do_fisico)}
                media.class = Audio/Source
                audio.position = [ MONO ]
            }}
        }}
    }}
]
"""


def config_wireplumber(nome_do_fisico: str, descricao_do_fisico: str) -> str:
    """`~/.config/wireplumber/wireplumber.conf.d/50-jarvis-microfone.conf`: o físico ganha outro
    nome e descrição («direto, só o Jarvis»), para a fonte virtual ficar com os originais."""
    return f"""# Gerado pelo Jarvis (ADR-0074, modo instalado). Apague este arquivo para desfazer.
monitor.alsa.rules = [
    {{
        matches = [ {{ node.name = {_spa(nome_do_fisico)} }} ]
        actions = {{
            update-props = {{
                node.name = {_spa(nome_do_fisico + SUFIXO_DO_FISICO)}
                node.description = {_spa(descricao_do_fisico + " (direto, só o Jarvis)")}
            }}
        }}
    }}
]
"""


SERVICOS: Final = ("wireplumber", "pipewire", "pipewire-pulse")


@dataclass(slots=True)
class Instalacao:
    """Os dois arquivos do modo instalado, com cópia do que existia e desfazer."""

    executor: Executor
    pasta_pipewire: Path
    pasta_wireplumber: Path

    def _arquivos(self) -> tuple[Path, Path]:
        return (
            self.pasta_pipewire / ARQUIVO_DE_CONFIGURACAO,
            self.pasta_wireplumber / ARQUIVO_DE_CONFIGURACAO,
        )

    def previa(self, nome_do_fisico: str, descricao_do_fisico: str) -> dict[str, str]:
        """O que seria gravado, para o dono ver antes do sim."""
        pipewire, wireplumber = self._arquivos()
        return {
            str(pipewire.name) + " (pipewire)": config_pipewire(
                nome_do_fisico, descricao_do_fisico
            ),
            str(wireplumber.name) + " (wireplumber)": config_wireplumber(
                nome_do_fisico, descricao_do_fisico
            ),
        }

    def instalar(self, nome_do_fisico: str, descricao_do_fisico: str, *, confirmado: bool) -> None:
        if not confirmado:
            raise ErroDoMisturador("o modo instalado só grava com o sim do dono")
        if not nome_do_fisico or nome_do_fisico.endswith(SUFIXO_DO_FISICO):
            raise ErroDoMisturador("nome do microfone físico inválido")
        conteudos = (
            config_pipewire(nome_do_fisico, descricao_do_fisico),
            config_wireplumber(nome_do_fisico, descricao_do_fisico),
        )
        for caminho, conteudo in zip(self._arquivos(), conteudos, strict=True):
            caminho.parent.mkdir(parents=True, exist_ok=True)
            copia = caminho.with_name(caminho.name + ".antes-do-jarvis")
            if caminho.exists() and not copia.exists():
                caminho.replace(copia)
            caminho.write_text(conteudo, encoding="utf-8")
        self._reiniciar()

    def desinstalar(self) -> None:
        for caminho in self._arquivos():
            copia = caminho.with_name(caminho.name + ".antes-do-jarvis")
            if copia.exists():
                copia.replace(caminho)
            else:
                caminho.unlink(missing_ok=True)
        self._reiniciar()

    def _reiniciar(self) -> None:
        saida = self.executor.rodar(("systemctl", "--user", "restart", *SERVICOS))
        if saida.codigo != 0:
            raise ErroDoMisturador(f"reiniciar o áudio falhou: {saida.texto.strip()[:200]}")


__all__ = [
    "NOME_DA_FONTE",
    "NOME_DO_MIX",
    "ErroDoMisturador",
    "Executor",
    "ExecutorDoSistema",
    "Instalacao",
    "Misturador",
    "Saida",
    "config_pipewire",
    "config_wireplumber",
]
