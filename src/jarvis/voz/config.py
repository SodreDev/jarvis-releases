"""Configuração do `jarvis-voz`: um TOML do dono, sem segredo nenhum (ADR-0017, ADR-0018).

Três regras, e todas são do dono:

1. **Escolha dele, aplicada por código.** Motor de ASR, motor de TTS, voz, gerador de
   resposta, dispositivos e PTT × VAD vivem aqui. Nenhum deles é decidido por frase, por
   capacidade ou por variável de ambiente que qualquer processo possa exportar (P12, §5.5) —
   e é por isso que o interruptor da nuvem (`nuvem_ligada`) mora **neste arquivo** e é lido
   pelo aplicativo, não pelo portão.
2. **Nunca segredo.** A leitura passa por `proibir_segredo_na_configuracao`: campo com cara de
   chave, ou valor com forma de chave, faz o arquivo ser **recusado** em vez de carregado. A
   chave de API vem só do ambiente, e a tela de configuração mostra "definida/ausente" lendo o
   nome da variável — nunca o valor.
3. **Validação na leitura, não no uso.** Motor que não está no registro, gerador que não
   existe, modo de escuta inventado: tudo recusa aqui, com a lista do que é válido. Descobrir
   isso no meio de um turno seria descobrir tarde.

O arquivo fica no diretório de configuração do usuário (`$XDG_CONFIG_HOME/jarvis/`,
`~/.config/jarvis/` ou `%APPDATA%\\jarvis\\`), nunca no repositório.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.voz.chaves import proibir_segredo_na_configuracao
from jarvis.voz.interface import Onde
from jarvis.voz.registro import Motor, ler_motores, motor_registrado
from jarvis.voz.s2_provisorio import nomes_de_gerador

ARQUIVO: Final = "jarvis-voz.toml"
PASTA: Final = "jarvis"
VARIAVEL_CONFIG: Final = "JARVIS_VOZ_CONFIG"
"""Aponta para outro arquivo de configuração. Serve ao teste e a quem tem mais de um perfil."""

ASR_PADRAO: Final = "asr-whisper-local"
TTS_PADRAO: Final = "tts-piper-epitran"
S2_PADRAO: Final = "eco"
VOZ_PADRAO: Final = "pt_BR-faber-medium"
MODELO_DO_ASR_PADRAO: Final = "small"
ESCUTAS: Final[tuple[str, ...]] = ("ptt", "vad")


class ConfiguracaoInvalida(ValueError):
    """O arquivo existe e não serve. A mensagem diz o campo e o que é válido."""


def pasta_de_configuracao(ambiente: Mapping[str, str] | None = None) -> Path:
    """O diretório de configuração do usuário, pelo padrão de cada sistema (P11)."""
    fonte = ambiente_ou_os(ambiente)
    if os.name == "nt":  # pragma: no cover — caminho do Windows, sem CI aqui
        base = fonte.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = fonte.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / PASTA


def caminho_padrao(ambiente: Mapping[str, str] | None = None) -> Path:
    fonte = ambiente_ou_os(ambiente)
    escolhido = fonte.get(VARIAVEL_CONFIG, "").strip()
    return Path(escolhido) if escolhido else pasta_de_configuracao(ambiente) / ARQUIVO


@dataclass(frozen=True, slots=True)
class Configuracao:
    """O que o dono escolheu. Imutável: mudar é escrever um arquivo novo, não um campo."""

    asr: str = ASR_PADRAO
    tts: str = TTS_PADRAO
    s2: str = S2_PADRAO
    voz: str = VOZ_PADRAO
    """Voz do TTS: a voz do piper no caminho local, ou o `voice_id` da conta na ElevenLabs."""
    modelo_do_asr: str = MODELO_DO_ASR_PADRAO
    """Tamanho do whisper local. Na nuvem, o modelo é o do próprio motor registrado."""
    modelo_do_s2: str = ""
    entrada: str = ""
    """Dispositivo de captura: índice ou nome, como o `--diagnostico` lista. Vazio = padrão."""
    saida: str = ""
    escuta: str = "ptt"
    nuvem_ligada: tuple[str, ...] = ()
    """Os motores de nuvem que o dono ligou. Vazio = nada sai da máquina."""
    nuvem_sem_termos: tuple[str, ...] = ()
    """Motores que ele aceita usar **sem termos publicados** (hoje: `tts-edge`)."""

    def para_dict(self) -> dict[str, Any]:
        return {
            "asr": self.asr,
            "tts": self.tts,
            "s2": self.s2,
            "voz": self.voz,
            "modelo_do_asr": self.modelo_do_asr,
            "modelo_do_s2": self.modelo_do_s2,
            "entrada": self.entrada,
            "saida": self.saida,
            "escuta": self.escuta,
            "nuvem_ligada": list(self.nuvem_ligada),
            "nuvem_sem_termos": list(self.nuvem_sem_termos),
        }

    @property
    def usa_nuvem(self) -> bool:
        motores = {self.asr, self.tts}
        return any(
            (m := motor_registrado(identificador)) is not None and m.onde is Onde.NUVEM
            for identificador in motores
        )

    def motores_de_nuvem_escolhidos(self) -> tuple[Motor, ...]:
        """Os motores de nuvem que estão **em uso** nesta configuração — para o aviso."""
        escolhidos = []
        for identificador in (self.asr, self.tts):
            motor = motor_registrado(identificador)
            if motor is not None and motor.onde is Onde.NUVEM:
                escolhidos.append(motor)
        return tuple(escolhidos)

    def com(self, **mudancas: Any) -> Configuracao:
        return replace(self, **mudancas)


def _texto_toml(configuracao: Configuracao) -> str:
    """TOML escrito à mão: são onze campos e nenhuma dependência nova por isso."""

    def aspas(valor: str) -> str:
        return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def lista(valores: Sequence[str]) -> str:
        return "[" + ", ".join(aspas(v) for v in valores) + "]"

    return f"""# Configuração do `jarvis-voz` (ADR-0017, ADR-0018).
#
# **Nunca escreva chave de API aqui.** O aplicativo recusa o arquivo inteiro se achar algo
# com cara de segredo. As chaves vêm só do ambiente:
#   export JARVIS_GROQ_API_KEY=...
#   export JARVIS_ELEVENLABS_API_KEY=...
#
# `nuvem_ligada` é o interruptor da nuvem: motor que não estiver nesta lista **não** manda
# áudio nem texto para fora, mesmo escolhido. `nuvem_sem_termos` é mais forte ainda — é
# aceitar um serviço que não publica termos (hoje, só o `tts-edge` se encaixa nisso).

asr = {aspas(configuracao.asr)}
tts = {aspas(configuracao.tts)}
s2 = {aspas(configuracao.s2)}
voz = {aspas(configuracao.voz)}
modelo_do_asr = {aspas(configuracao.modelo_do_asr)}
modelo_do_s2 = {aspas(configuracao.modelo_do_s2)}
entrada = {aspas(configuracao.entrada)}
saida = {aspas(configuracao.saida)}
escuta = {aspas(configuracao.escuta)}
nuvem_ligada = {lista(configuracao.nuvem_ligada)}
nuvem_sem_termos = {lista(configuracao.nuvem_sem_termos)}
"""


def escrever(configuracao: Configuracao, caminho: Path) -> None:
    """Grava o TOML, criando a pasta. Confere que não há segredo **antes** de escrever."""
    proibir_segredo_na_configuracao(configuracao.para_dict(), arquivo=caminho.name)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(_texto_toml(configuracao), encoding="utf-8")


def _texto(dados: Mapping[str, Any], chave: str, padrao: str) -> str:
    valor = dados.get(chave, padrao)
    if not isinstance(valor, str):
        raise ConfiguracaoInvalida(f"{chave}: esperava texto, veio {type(valor).__name__}")
    return valor


def _lista(dados: Mapping[str, Any], chave: str) -> tuple[str, ...]:
    valor = dados.get(chave, [])
    if not isinstance(valor, list) or any(not isinstance(v, str) for v in valor):
        raise ConfiguracaoInvalida(f"{chave}: esperava lista de textos")
    return tuple(valor)


def validar(configuracao: Configuracao) -> Configuracao:
    """Recusa o que não existe, dizendo o que existe. Chamada na leitura e na gravação."""
    motores = {m.id: m for m in ler_motores()}

    def exigir(campo: str, identificador: str, papel: str) -> Motor:
        motor = motores.get(identificador)
        if motor is None or motor.papel != papel:
            validos = ", ".join(sorted(m.id for m in motores.values() if m.papel == papel))
            raise ConfiguracaoInvalida(
                f"{campo} = {identificador!r} não é um motor de {papel} registrado. "
                f"Válidos: {validos}"
            )
        return motor

    exigir("asr", configuracao.asr, "asr")
    exigir("tts", configuracao.tts, "tts")

    if configuracao.s2 not in nomes_de_gerador():
        raise ConfiguracaoInvalida(
            f"s2 = {configuracao.s2!r} não existe. Válidos: {', '.join(nomes_de_gerador())}"
        )
    if configuracao.escuta not in ESCUTAS:
        raise ConfiguracaoInvalida(
            f"escuta = {configuracao.escuta!r} não existe. Válidos: {', '.join(ESCUTAS)}"
        )
    for identificador in configuracao.nuvem_ligada:
        motor = motores.get(identificador)
        if motor is None:
            raise ConfiguracaoInvalida(
                f"nuvem_ligada tem {identificador!r}, que não está no registro de motores"
            )
        if motor.onde is not Onde.NUVEM:
            raise ConfiguracaoInvalida(
                f"nuvem_ligada tem {identificador!r}, que é motor **local**: ligar nuvem para "
                "ele não quer dizer nada, e deixar isso passar esconderia um engano"
            )
    for identificador in configuracao.nuvem_sem_termos:
        if identificador not in motores:
            raise ConfiguracaoInvalida(
                f"nuvem_sem_termos tem {identificador!r}, que não está no registro de motores"
            )
    return configuracao


def ler(caminho: Path | None = None, *, ambiente: Mapping[str, str] | None = None) -> Configuracao:
    """A configuração do dono, ou os padrões quando ainda não há arquivo.

    Arquivo ausente **não** é erro: o primeiro uso do aplicativo tem de funcionar sem o dono
    ter escrito nada — com tudo local e nada saindo da máquina.
    """
    alvo = caminho if caminho is not None else caminho_padrao(ambiente)
    if not alvo.exists():
        return Configuracao()
    try:
        dados = tomllib.loads(alvo.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as erro:
        raise ConfiguracaoInvalida(f"{alvo} não deu para ler: {erro}") from None
    proibir_segredo_na_configuracao(dados, arquivo=str(alvo))
    configuracao = Configuracao(
        asr=_texto(dados, "asr", ASR_PADRAO),
        tts=_texto(dados, "tts", TTS_PADRAO),
        s2=_texto(dados, "s2", S2_PADRAO),
        voz=_texto(dados, "voz", VOZ_PADRAO),
        modelo_do_asr=_texto(dados, "modelo_do_asr", MODELO_DO_ASR_PADRAO),
        modelo_do_s2=_texto(dados, "modelo_do_s2", ""),
        entrada=_texto(dados, "entrada", ""),
        saida=_texto(dados, "saida", ""),
        escuta=_texto(dados, "escuta", "ptt"),
        nuvem_ligada=_lista(dados, "nuvem_ligada"),
        nuvem_sem_termos=_lista(dados, "nuvem_sem_termos"),
    )
    return validar(configuracao)


@dataclass(frozen=True, slots=True)
class Aviso:
    """Um aviso para a tela: o que o dono precisa ler antes de confirmar."""

    motor: str
    frase: str


def avisos_de_nuvem(configuracao: Configuracao) -> tuple[Aviso, ...]:
    """Os avisos obrigatórios dos motores de nuvem escolhidos (ADR-0017, política 3)."""
    return tuple(
        Aviso(motor=motor.id, frase=motor.frase_de_aviso)
        for motor in configuracao.motores_de_nuvem_escolhidos()
    )


MOTORES_POR_PAPEL: Final[dict[str, str]] = {"asr": "ASR", "tts": "TTS"}
