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
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.voz.chaves import proibir_segredo_na_configuracao
from jarvis.voz.escuta import MODOS, CombinacaoInvalida, exigir_combinacao
from jarvis.voz.interface import Onde
from jarvis.voz.palavra import (
    LIMIAR_PADRAO,
    PALAVRA_PADRAO,
    PalavraInvalida,
    exigir_limiar,
    exigir_palavra,
)
from jarvis.voz.registro import Motor, MotorRecusado, exigir_modelo, ler_motores, motor_registrado
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
ESCUTAS: Final[tuple[str, ...]] = MODOS
"""`ptt` (atalho de teclas), `palavra` (palavra de ativação) e `vad` (escuta contínua)."""
TTS_ELEVENLABS: Final = "tts-elevenlabs"
FORMA_DO_ID_DE_VOZ: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]{1,64}")
"""O `voice_id` vai **no caminho** da URL (`/v1/text-to-speech/{voice_id}`): barra, `?`, `#`
ou espaço mudariam o pedido. Os ids da ElevenLabs são alfanuméricos; o resto recusa."""
FORMA_DA_VOZ_DO_PIPER: Final[re.Pattern[str]] = re.compile(r"[a-z]{2,3}_[A-Z]{2}-.+")
"""`pt_BR-faber-medium`: idioma_PAÍS-nome-qualidade, como o rhasspy/piper-voices nomeia."""


ACESSO_PADRAO: Final = "jarvis"
"""Padrão da fatia 6 (pedido do dono): nenhuma pasta dele — só a área do Jarvis."""
ACESSOS: Final[tuple[str, ...]] = ("jarvis", "padrao", "concedido", "total")
FORMA_DA_FAMILIA: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
"""O nome curto de um navegador na configuração (`firefox`, `brave`)."""
FORMA_DO_APP: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
FORMA_DO_DOMINIO: Final[re.Pattern[str]] = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,63}")


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
    """Voz do piper, no caminho local. A da ElevenLabs tem campo próprio (`voz_elevenlabs`)."""
    voz_elevenlabs: str = ""
    """O `voice_id` da conta do dono na ElevenLabs. Vazio = não escolhida (o motor recusa)."""
    modelo_elevenlabs: str = ""
    """Modelo da ElevenLabs, da lista do registro. Vazio = o padrão do registro."""
    modelo_do_asr: str = MODELO_DO_ASR_PADRAO
    """Tamanho do whisper local. Na nuvem, o modelo é o do próprio motor registrado."""
    modelo_do_s2: str = ""
    entrada: str = ""
    """Dispositivo de captura: índice ou nome, como o `--diagnostico` lista. Vazio = padrão."""
    saida: str = ""
    escuta: str = "ptt"
    palavra: str = PALAVRA_PADRAO
    """A palavra de ativação do modo `palavra` (ADR-0021)."""
    limiar_palavra: float = LIMIAR_PADRAO
    """O quanto a transcrição tem de soar como a palavra, de 0,50 a 1,0."""
    atalho: str = ""
    """A combinação de teclas do modo `ptt`, na grafia do Qt. Vazio = barra de espaço."""
    atalho_global: bool = False
    """O dono pediu o atalho **global** (portal do sistema) e o sistema aceitou: a janela pede
    de novo ao abrir. Antes isto não era guardado, e o atalho global sumia a cada reinício."""
    enderecamento: str = ""
    """O motor de decisão que diz se uma fala é para o Jarvis (ADR-0029): hoje só
    `decisao-jev-openrouter`. Vazio = desligado, e na escuta contínua todo trecho segue virando
    pedido. Motor de nuvem: também precisa estar em `nuvem_ligada` — escolher não liga."""
    nuvem_ligada: tuple[str, ...] = ()
    """Os motores de nuvem que o dono ligou. Vazio = nada sai da máquina."""
    nuvem_sem_termos: tuple[str, ...] = ()
    """Motores que ele aceita usar **sem termos publicados** (hoje: `tts-edge`)."""
    acesso: str = ACESSO_PADRAO
    """O modo de acesso da §5.5 (P12: escolha do dono). `jarvis` = só a área do Jarvis."""
    raizes: tuple[str, ...] = ()
    """Pastas concedidas uma a uma, **só leitura**, que valem no modo `concedido`."""
    raizes_escrita: tuple[str, ...] = ()
    """Subconjunto de `raizes` com nível **leitura e escrita**. As outras ficam só de leitura. Hoje
    nenhuma ferramenta grava fora da pasta do Jarvis: o nível fica guardado e o PDP já o respeita
    (`pode_escrever`), para a primeira ferramenta que escrever numa raiz concedida."""
    apps_autorizados: tuple[str, ...] = ()
    """Ids de `.desktop` que `apps.launch` pode abrir (ex.: `org.kde.dolphin`). Vazio = nenhum."""
    apps_extras: tuple[str, ...] = ()
    """Apps que o dono escolheu à mão: caminho de um `.desktop` ou de um binário. Cada um vale
    como autorizado; o nome com que se chama é o do arquivo."""
    navegadores: tuple[str, ...] = ()
    """Os navegadores que o dono configurou, cada um `família=caminho` (um binário ou um
    `.desktop`): `firefox=/usr/bin/firefox`. Vazio = `sites.open` usa o padrão do desktop."""
    navegador_principal: str = ""
    """A família (de `navegadores`) onde `sites.open` abre quando o pedido não nomeia outro."""
    sites_sem_confirmar: tuple[str, ...] = ()
    """Domínios que `sites.open` abre mesmo depois de o turno ler conteúdo de terceiros (com
    subdomínios). Abrir site é livre; esta lista só tira a confirmação desse caso."""
    tarefa_motor: str = "direto"
    """Quem conduz as tarefas em segundo plano (ADR-0022): `direto` roda a ferramenta pedida;
    `agente` deixa o motor de conversa (`s2`) planejar os passos — e, se o `s2` é de nuvem, a
    tarefa também vai para a nuvem. **Só o dono escolhe**: nenhuma tool tem este campo."""
    laco_max_passos: int = 12
    """Teto de chamadas de ferramenta encadeadas num turno (1 a 50). Só o dono escolhe."""
    laco_prazo_s: float = 90.0
    """Teto, em segundos, do encadeamento inteiro de um turno (5 a 600). Só o dono escolhe."""

    def para_dict(self) -> dict[str, Any]:
        return {
            "asr": self.asr,
            "tts": self.tts,
            "s2": self.s2,
            "voz": self.voz,
            "voz_elevenlabs": self.voz_elevenlabs,
            "modelo_elevenlabs": self.modelo_elevenlabs,
            "modelo_do_asr": self.modelo_do_asr,
            "modelo_do_s2": self.modelo_do_s2,
            "entrada": self.entrada,
            "saida": self.saida,
            "escuta": self.escuta,
            "palavra": self.palavra,
            "limiar_palavra": self.limiar_palavra,
            "atalho": self.atalho,
            "atalho_global": self.atalho_global,
            "enderecamento": self.enderecamento,
            "nuvem_ligada": list(self.nuvem_ligada),
            "nuvem_sem_termos": list(self.nuvem_sem_termos),
            "acesso": self.acesso,
            "raizes": list(self.raizes),
            "raizes_escrita": list(self.raizes_escrita),
            "apps_autorizados": list(self.apps_autorizados),
            "apps_extras": list(self.apps_extras),
            "navegadores": list(self.navegadores),
            "navegador_principal": self.navegador_principal,
            "sites_sem_confirmar": list(self.sites_sem_confirmar),
            "tarefa_motor": self.tarefa_motor,
            "laco_max_passos": self.laco_max_passos,
            "laco_prazo_s": self.laco_prazo_s,
        }

    @property
    def usa_nuvem(self) -> bool:
        motores = {self.asr, self.tts, *([self.enderecamento] if self.enderecamento else [])}
        return any(
            (m := motor_registrado(identificador)) is not None and m.onde is Onde.NUVEM
            for identificador in motores
        )

    def motores_de_nuvem_escolhidos(self) -> tuple[Motor, ...]:
        """Os motores de nuvem que estão **em uso** nesta configuração — para o aviso."""
        escolhidos = []
        for identificador in (self.asr, self.tts, self.enderecamento):
            motor = motor_registrado(identificador) if identificador else None
            if motor is not None and motor.onde is Onde.NUVEM:
                escolhidos.append(motor)
        return tuple(escolhidos)

    def com(self, **mudancas: Any) -> Configuracao:
        return replace(self, **mudancas)


def _texto_toml(configuracao: Configuracao) -> str:
    """TOML escrito à mão: são dezesseis campos e nenhuma dependência nova por isso."""

    def aspas(valor: str) -> str:
        return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def lista(valores: Sequence[str]) -> str:
        return "[" + ", ".join(aspas(v) for v in valores) + "]"

    return f"""# Configuração do `jarvis-voz` (ADR-0017, ADR-0018).
#
# **Nunca escreva chave de API aqui.** O aplicativo recusa o arquivo inteiro se achar algo
# com cara de segredo. As chaves vêm só do ambiente ou do chaveiro do sistema:
#   export JARVIS_GROQ_API_KEY=...
#   export JARVIS_ELEVENLABS_API_KEY=...
#   export OPENROUTER_API_KEY=...
#
# `nuvem_ligada` é o interruptor da nuvem: motor que não estiver nesta lista **não** manda
# áudio nem texto para fora, mesmo escolhido. `nuvem_sem_termos` é mais forte ainda — é
# aceitar um serviço que não publica termos (hoje, só o `tts-edge` se encaixa nisso).

asr = {aspas(configuracao.asr)}
tts = {aspas(configuracao.tts)}
s2 = {aspas(configuracao.s2)}
voz = {aspas(configuracao.voz)}
voz_elevenlabs = {aspas(configuracao.voz_elevenlabs)}
modelo_elevenlabs = {aspas(configuracao.modelo_elevenlabs)}
modelo_do_asr = {aspas(configuracao.modelo_do_asr)}
modelo_do_s2 = {aspas(configuracao.modelo_do_s2)}
entrada = {aspas(configuracao.entrada)}
saida = {aspas(configuracao.saida)}
escuta = {aspas(configuracao.escuta)}
palavra = {aspas(configuracao.palavra)}
limiar_palavra = {configuracao.limiar_palavra!r}
atalho = {aspas(configuracao.atalho)}
atalho_global = {"true" if configuracao.atalho_global else "false"}
# Detector de endereçamento (ADR-0029): "" = desligado. Com "decisao-jev-openrouter" a fala
# transcrita de cada trecho da escuta contínua vai ao OpenRouter para saber se é com o Jarvis
# (precisa também estar em nuvem_ligada e da chave OPENROUTER_API_KEY).
enderecamento = {aspas(configuracao.enderecamento)}
nuvem_ligada = {lista(configuracao.nuvem_ligada)}
nuvem_sem_termos = {lista(configuracao.nuvem_sem_termos)}

# O que o Jarvis pode tocar (SPEC §5.5, ADR-0028). `acesso`: "jarvis" (só a área dele — o
# padrão), "padrao" (+ Documentos, Downloads, Imagens, Música, Vídeos, Área de Trabalho),
# "concedido" (+ as `raizes`, só leitura) ou "total". Chaves, cofres e perfis de navegador
# ficam negados em qualquer modo. Escrever, só rascunho na pasta do Jarvis, com confirmação.
acesso = {aspas(configuracao.acesso)}
raizes = {lista(configuracao.raizes)}
# As que, entre as `raizes`, também podem ser escritas (as outras são só de leitura).
raizes_escrita = {lista(configuracao.raizes_escrita)}
# Apps que "abrir o Dolphin" pode abrir: o id do .desktop (ls /usr/share/applications).
apps_autorizados = {lista(configuracao.apps_autorizados)}
# Apps escolhidos à mão: caminho de um .desktop ou de um binário.
apps_extras = {lista(configuracao.apps_extras)}
# Navegadores, "família=caminho" (binário ou .desktop), e qual é o principal.
navegadores = {lista(configuracao.navegadores)}
navegador_principal = {aspas(configuracao.navegador_principal)}
# Abrir site é livre; estes continuam livres mesmo depois de o Jarvis ler um arquivo ou página
# (nesse caso, qualquer outro pede o seu sim). Ex.: ["wikipedia.org"]
sites_sem_confirmar = {lista(configuracao.sites_sem_confirmar)}
# Quem conduz as tarefas em segundo plano: "direto" (roda a ferramenta pedida) ou "agente"
# (o motor de conversa planeja os passos; se ele é de nuvem, a tarefa vai junto).
tarefa_motor = {aspas(configuracao.tarefa_motor)}
# Laço de ferramentas: quantas chamadas encadeadas num turno (1 a 50) e quantos segundos (5 a 600).
laco_max_passos = {configuracao.laco_max_passos}
laco_prazo_s = {configuracao.laco_prazo_s}
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


def _numero(dados: Mapping[str, Any], chave: str, padrao: float) -> float:
    valor = dados.get(chave, padrao)
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise ConfiguracaoInvalida(f"{chave}: esperava número, veio {type(valor).__name__}")
    return float(valor)


def _inteiro(dados: Mapping[str, Any], chave: str, padrao: int) -> int:
    valor = dados.get(chave, padrao)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ConfiguracaoInvalida(f"{chave}: esperava inteiro, veio {type(valor).__name__}")
    return int(valor)


def _logico(dados: Mapping[str, Any], chave: str) -> bool:
    valor = dados.get(chave, False)
    if not isinstance(valor, bool):
        raise ConfiguracaoInvalida(f"{chave}: esperava true ou false, veio {type(valor).__name__}")
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
    if configuracao.enderecamento:
        exigir("enderecamento", configuracao.enderecamento, "decisao")

    if not 1 <= configuracao.laco_max_passos <= 50:
        raise ConfiguracaoInvalida(
            f"laco_max_passos = {configuracao.laco_max_passos} fora de 1 a 50"
        )
    if not 5 <= configuracao.laco_prazo_s <= 600:
        raise ConfiguracaoInvalida(f"laco_prazo_s = {configuracao.laco_prazo_s} fora de 5 a 600")
    if configuracao.tarefa_motor not in ("direto", "agente"):
        raise ConfiguracaoInvalida(
            f"tarefa_motor = {configuracao.tarefa_motor!r} não existe. Os que existem: "
            "direto, agente"
        )
    if configuracao.voz_elevenlabs and not FORMA_DO_ID_DE_VOZ.fullmatch(
        configuracao.voz_elevenlabs
    ):
        raise ConfiguracaoInvalida(
            f"voz_elevenlabs = {configuracao.voz_elevenlabs!r} não tem a forma de um voice_id "
            "(letras, números, _ e -, até 64): ele vai no caminho da URL do serviço"
        )
    elevenlabs = motores.get(TTS_ELEVENLABS)
    if configuracao.modelo_elevenlabs:
        if elevenlabs is None:
            raise ConfiguracaoInvalida(f"modelo_elevenlabs sem o motor {TTS_ELEVENLABS!r}")
        try:
            exigir_modelo(elevenlabs, configuracao.modelo_elevenlabs)
        except MotorRecusado as erro:
            raise ConfiguracaoInvalida(f"modelo_elevenlabs: {erro}") from None

    if configuracao.s2 not in nomes_de_gerador():
        raise ConfiguracaoInvalida(
            f"s2 = {configuracao.s2!r} não existe. Válidos: {', '.join(nomes_de_gerador())}"
        )
    if configuracao.escuta not in ESCUTAS:
        raise ConfiguracaoInvalida(
            f"escuta = {configuracao.escuta!r} não existe. Válidos: {', '.join(ESCUTAS)}"
        )
    try:
        exigir_palavra(configuracao.palavra)
        exigir_limiar(configuracao.limiar_palavra)
        exigir_combinacao(configuracao.atalho)
    except (PalavraInvalida, CombinacaoInvalida) as erro:
        raise ConfiguracaoInvalida(str(erro)) from None
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
    if configuracao.acesso not in ACESSOS:
        raise ConfiguracaoInvalida(
            f"acesso = {configuracao.acesso!r} não existe. Válidos: {', '.join(ACESSOS)}"
        )
    for raiz in configuracao.raizes:
        if not Path(raiz).expanduser().is_absolute():
            raise ConfiguracaoInvalida(f"raizes tem {raiz!r}: use o caminho inteiro (~/Projetos)")
    for raiz in configuracao.raizes_escrita:
        if raiz not in configuracao.raizes:
            raise ConfiguracaoInvalida(
                f"raizes_escrita tem {raiz!r}, que não está em raizes: o nível de escrita é de "
                "uma pasta já concedida"
            )
    for extra in configuracao.apps_extras:
        if not Path(extra).expanduser().is_absolute():
            raise ConfiguracaoInvalida(f"apps_extras tem {extra!r}: use o caminho inteiro")
    familias: set[str] = set()
    for entrada in configuracao.navegadores:
        familia, _, caminho_do_navegador = entrada.partition("=")
        if (
            not FORMA_DA_FAMILIA.fullmatch(familia)
            or not Path(caminho_do_navegador).expanduser().is_absolute()
        ):
            raise ConfiguracaoInvalida(
                f"navegadores tem {entrada!r}: use família=caminho (firefox=/usr/bin/firefox)"
            )
        familias.add(familia)
    if configuracao.navegador_principal and configuracao.navegador_principal not in familias:
        raise ConfiguracaoInvalida(
            f"navegador_principal = {configuracao.navegador_principal!r} não está em navegadores"
        )
    for app in configuracao.apps_autorizados:
        if not FORMA_DO_APP.fullmatch(app):
            raise ConfiguracaoInvalida(
                f"apps_autorizados tem {app!r}: use o id do .desktop (ex.: org.kde.dolphin)"
            )
    for site in configuracao.sites_sem_confirmar:
        if not FORMA_DO_DOMINIO.fullmatch(site):
            raise ConfiguracaoInvalida(
                f"sites_sem_confirmar tem {site!r}: use só o domínio (ex.: wikipedia.org)"
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
    tts = _texto(dados, "tts", TTS_PADRAO)
    voz = _texto(dados, "voz", VOZ_PADRAO)
    voz_elevenlabs = _texto(dados, "voz_elevenlabs", "")
    # Arquivo de antes do campo próprio: a tela de então mandava pôr o `voice_id` em `voz`.
    # Se o que está lá não tem forma de voz do piper, é o id da ElevenLabs.
    antigo = "voz_elevenlabs" not in dados and tts == TTS_ELEVENLABS
    if antigo and voz and not FORMA_DA_VOZ_DO_PIPER.fullmatch(voz):
        voz_elevenlabs, voz = voz, VOZ_PADRAO
    configuracao = Configuracao(
        asr=_texto(dados, "asr", ASR_PADRAO),
        tts=tts,
        s2=_texto(dados, "s2", S2_PADRAO),
        voz=voz,
        voz_elevenlabs=voz_elevenlabs,
        modelo_elevenlabs=_texto(dados, "modelo_elevenlabs", ""),
        modelo_do_asr=_texto(dados, "modelo_do_asr", MODELO_DO_ASR_PADRAO),
        modelo_do_s2=_texto(dados, "modelo_do_s2", ""),
        entrada=_texto(dados, "entrada", ""),
        saida=_texto(dados, "saida", ""),
        escuta=_texto(dados, "escuta", "ptt"),
        palavra=_texto(dados, "palavra", PALAVRA_PADRAO),
        limiar_palavra=_numero(dados, "limiar_palavra", LIMIAR_PADRAO),
        atalho=_texto(dados, "atalho", ""),
        atalho_global=_logico(dados, "atalho_global"),
        enderecamento=_texto(dados, "enderecamento", ""),
        nuvem_ligada=_lista(dados, "nuvem_ligada"),
        nuvem_sem_termos=_lista(dados, "nuvem_sem_termos"),
        acesso=_texto(dados, "acesso", ACESSO_PADRAO),
        raizes=_lista(dados, "raizes"),
        raizes_escrita=_lista(dados, "raizes_escrita"),
        apps_autorizados=_lista(dados, "apps_autorizados"),
        apps_extras=_lista(dados, "apps_extras"),
        navegadores=_lista(dados, "navegadores"),
        navegador_principal=_texto(dados, "navegador_principal", ""),
        sites_sem_confirmar=tuple(s.lower() for s in _lista(dados, "sites_sem_confirmar")),
        tarefa_motor=_texto(dados, "tarefa_motor", "direto"),
        laco_max_passos=_inteiro(dados, "laco_max_passos", 12),
        laco_prazo_s=_numero(dados, "laco_prazo_s", 90.0),
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
