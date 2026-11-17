"""`chamada.toml`: os ajustes da voz do Jarvis na ligação (ADR-0074). Padrões seguros.

    duracao_para_aviso_min = 5      # passou: o agente é AVISADO (não há corte automático)
    turnos = 30                     # passou: o agente é avisado e decide
    frases_por_fala = 5             # teto de cada `chamada.falar` (a fala maior volta recusada)
    tentativas_de_codigo = 3        # códigos errados por chamada antes de o agente ser avisado
    canal_de_confirmacao = "sessao_do_pc"
    pode_dizer = ""                 # o que o dono deixa o Jarvis contar a quem liga
    nunca_dizer = "onde o dono está, com quem está, a agenda dele, dados pessoais"
    palavra_de_coacao = ""          # vazio = desligada
    retencao_do_recado_dias = 30
    retencao_da_memoria_dias = 30
    lembrar_interlocutor = true
    usa_fone = false

Decisões do dono (2026-11-17): 5 min **sem** encerramento automático — passado o tempo, o
Jarvis avisa a pessoa ou o dono; até 30 turnos; até 5 frases por fala; o Jarvis lembra do
interlocutor entre chamadas, mas pede o TOTP a cada chamada a quem disser ser o dono. O que só o
dono responde (o canal de confirmação, o texto que pode e não pode ser dito, o fone, a palavra de
coação, a retenção) é ajuste com padrão seguro.

O arquivo mora ao lado do `jarvis-voz.toml`, 0600. Chave desconhecida ou valor fora do tipo
recusa o arquivo inteiro com o campo na mensagem (como `redes.toml`)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Final

from jarvis.social.arquivo import escrever_privado, texto_toml

ARQUIVO: Final = "chamada.toml"
CANAIS_DE_CONFIRMACAO: Final = ("sessao_do_pc",)
"""Por onde uma ação pedida na chamada é confirmada. Só a sessão aberta no PC, por ora: a
mensagem ao próprio dono no WhatsApp é a outra opção do estudo e espera a decisão dele."""
TEXTO_MAXIMO: Final = 400


class ConfiguracaoDaChamadaInvalida(ValueError):
    """O arquivo tem chave desconhecida ou valor fora do tipo/faixa."""


@dataclass(frozen=True, slots=True)
class ConfiguracaoDaChamada:
    duracao_para_aviso_min: int = 5
    turnos: int = 30
    frases_por_fala: int = 5
    tentativas_de_codigo: int = 3
    canal_de_confirmacao: str = "sessao_do_pc"
    pode_dizer: str = ""
    """O que o dono deixa contar (ex.: «está em reunião até as 15h»). Vazio: só que ele não
    pode atender agora."""
    nunca_dizer: str = "onde o dono está, com quem está, a agenda dele, dados pessoais"
    palavra_de_coacao: str = ""
    """Vazio = desligada. Ligada, entra no prompt do agente da chamada (decisão do dono)."""
    retencao_do_recado_dias: int = 30
    retencao_da_memoria_dias: int = 30
    lembrar_interlocutor: bool = True
    usa_fone: bool = False
    """Sem fone, a voz do Jarvis não toca no alto-falante durante a chamada (eco, §1.3)."""

    def __post_init__(self) -> None:
        faixas = {
            "duracao_para_aviso_min": (1, 120),
            "turnos": (1, 500),
            "frases_por_fala": (1, 20),
            "tentativas_de_codigo": (1, 10),
            "retencao_do_recado_dias": (0, 3650),
            "retencao_da_memoria_dias": (0, 3650),
        }
        for nome, (minimo, maximo) in faixas.items():
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int):
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: tem de ser um número inteiro")
            if not minimo <= valor <= maximo:
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: fora de {minimo}..{maximo}")
        for nome in ("pode_dizer", "nunca_dizer", "palavra_de_coacao", "canal_de_confirmacao"):
            valor = getattr(self, nome)
            if not isinstance(valor, str) or len(valor) > TEXTO_MAXIMO:
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: texto de até {TEXTO_MAXIMO}")
        for nome in ("lembrar_interlocutor", "usa_fone"):
            if not isinstance(getattr(self, nome), bool):
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: tem de ser true ou false")
        if self.canal_de_confirmacao not in CANAIS_DE_CONFIRMACAO:
            raise ConfiguracaoDaChamadaInvalida(
                f"canal_de_confirmacao: um de {', '.join(CANAIS_DE_CONFIRMACAO)}"
            )


def de_dict(dados: dict[str, Any]) -> ConfiguracaoDaChamada:
    conhecidos = {f.name for f in fields(ConfiguracaoDaChamada)}
    desconhecidos = sorted(set(dados) - conhecidos)
    if desconhecidos:
        raise ConfiguracaoDaChamadaInvalida(f"chave desconhecida: {', '.join(desconhecidos)}")
    return ConfiguracaoDaChamada(**dados)


def ler(caminho: Path) -> ConfiguracaoDaChamada:
    """O arquivo, validado. Sem arquivo: os padrões."""
    try:
        texto_do_arquivo = caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ConfiguracaoDaChamada()
    try:
        dados = tomllib.loads(texto_do_arquivo)
    except tomllib.TOMLDecodeError as erro:
        raise ConfiguracaoDaChamadaInvalida(f"{caminho.name}: TOML inválido ({erro})") from None
    return de_dict(dados)


def texto(configuracao: ConfiguracaoDaChamada) -> str:
    linhas = [
        "# A voz do Jarvis na ligação (ADR-0074). Gravado pela aba «chamadas» a cada mudança.",
        "# Arquivo pessoal (0600): não versionar. O segredo do TOTP NÃO mora aqui (chaveiro).",
        "",
    ]
    for campo in fields(ConfiguracaoDaChamada):
        valor = getattr(configuracao, campo.name)
        if isinstance(valor, bool):
            linhas.append(f"{campo.name} = {'true' if valor else 'false'}")
        elif isinstance(valor, int):
            linhas.append(f"{campo.name} = {valor}")
        else:
            linhas.append(f"{campo.name} = {texto_toml(str(valor))}")
    return "\n".join(linhas) + "\n"


def gravar(configuracao: ConfiguracaoDaChamada, caminho: Path) -> None:
    conteudo = texto(configuracao)
    if de_dict(tomllib.loads(conteudo)) != configuracao:  # pragma: no cover — contrato interno
        raise ConfiguracaoDaChamadaInvalida("o texto gravado não volta igual ao ajuste")
    escrever_privado(caminho, conteudo)


__all__ = [
    "ARQUIVO",
    "ConfiguracaoDaChamada",
    "ConfiguracaoDaChamadaInvalida",
    "gravar",
    "ler",
    "texto",
]
