"""`chamada.toml`: os ajustes da voz do Jarvis na ligação (ADR-0074). Padrões seguros.

    chamadas_ativas = false         # a chave mestra: desligada até o dono testar e ligar
    duracao_para_aviso_min = 5      # passou: o agente é AVISADO (não há corte automático)
    turnos = 30                     # passou: o agente é avisado e decide
    frases_por_fala = 5             # teto de cada `chamada.falar` (a fala maior volta recusada)
    tentativas_de_codigo = 3        # códigos errados por chamada antes de o agente ser avisado
    pode_dizer = "..."              # o critério do dono do que NÃO é sensível (o agente julga)
    nunca_dizer = "..."             # o critério do dono do que é sensível
    palavra_de_coacao = ""          # vazio = desligada (só o gancho; fora da aba, decisão do dono)
    retencao_do_recado_dias = 90
    retencao_da_memoria_dias = 90
    lembrar_interlocutor = true
    fone = "auto"                   # "sim", "nao" ou "auto" (o que o sistema diz da saída)
    contato_do_dono_whatsapp = ""   # o chat de destino COMO APARECE no WhatsApp Web (o do dono
                                    # ou o de um 2º número dele)
    acao_expira_min = 10            # ação pedida na chamada sem confirmação some depois disto

Decisões do dono (2026-11-17): 5 min **sem** encerramento automático — passado o tempo, o
Jarvis avisa a pessoa ou o dono; até 30 turnos; até 5 frases por fala; o Jarvis lembra do
interlocutor entre chamadas, mas pede o TOTP a cada chamada a quem disser ser o dono. Respostas
do dono às escolhas da ADR-0074 (2026-11-17, segunda rodada): (1) além da sessão do PC, a ação
pedida na chamada é confirmada por **mensagem ao próprio dono no WhatsApp** — ligada só quando
`contato_do_dono_whatsapp` está preenchido; vazio, vale só a sessão do PC; (2) a quem liga, só o
que não for sensível, pelo julgamento do agente com o critério de `pode_dizer`/`nunca_dizer`;
(3) fone às vezes: `fone` sim/não/auto; (4) palavra de coação desligada e fora da aba; (5)
retenção de 90 dias, configurável.

O arquivo mora ao lado do `jarvis-voz.toml`, 0600. Chave desconhecida ou valor fora do tipo
recusa o arquivo inteiro com o campo na mensagem (como `redes.toml`). As chaves antigas
`usa_fone` (vira `fone`) e `canal_de_confirmacao` (o canal agora sai do contato configurado) são
aceitas na leitura e somem na próxima gravação."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Final

from jarvis.social.arquivo import escrever_privado, texto_toml

ARQUIVO: Final = "chamada.toml"
SESSAO_DO_PC: Final = "sessao_do_pc"
WHATSAPP_DO_DONO: Final = "whatsapp_do_dono"
FONES: Final = ("sim", "nao", "auto")
TEXTO_MAXIMO: Final = 400
NOME_MAXIMO: Final = 80
PODE_DIZER_PADRAO: Final = (
    "que você é o assistente virtual do dono, que ele não pode atender agora, que você anota "
    "o recado e o passa a ele; informações públicas ou neutras"
)
NUNCA_DIZER_PADRAO: Final = (
    "onde o dono está ou vai estar, a agenda e os compromissos dele, com quem ele está, dados "
    "pessoais ou financeiros dele ou de outros; nem confirmar se este número é mesmo do dono ou "
    "se alguém é contato dele"
)
CHAVES_ANTIGAS: Final = frozenset({"usa_fone", "canal_de_confirmacao"})


class ConfiguracaoDaChamadaInvalida(ValueError):
    """O arquivo tem chave desconhecida ou valor fora do tipo/faixa."""


@dataclass(frozen=True, slots=True)
class ConfiguracaoDaChamada:
    chamadas_ativas: bool = False
    """A chave mestra (decisão do dono, 2026-11-17): desligada, nada da chamada roda — nem o
    canal do dono, nem o tique, nem chamada nova. O dono liga na aba depois de testar."""
    duracao_para_aviso_min: int = 5
    turnos: int = 30
    frases_por_fala: int = 5
    tentativas_de_codigo: int = 3
    pode_dizer: str = PODE_DIZER_PADRAO
    """O critério do dono do que pode ser dito a quem liga. Vai ao prompt; quem decide cada fala
    é o agente (julgamento do modelo), nunca uma lista de frases no código."""
    nunca_dizer: str = NUNCA_DIZER_PADRAO
    palavra_de_coacao: str = ""
    """Vazio = desligada. Decisão do dono (2026-11-17): por ora desligada e fora da aba; fica só o
    gancho — preenchida à mão no arquivo, entra no prompt do agente da chamada."""
    retencao_do_recado_dias: int = 90
    retencao_da_memoria_dias: int = 90
    lembrar_interlocutor: bool = True
    fone: str = "auto"
    """«sim»: a voz do Jarvis também toca no fone e o microfone real fica aberto; «nao»: a voz
    vai só à fonte virtual e o microfone real é abafado enquanto o Jarvis fala (eco, §1.3 do
    estudo); «auto»: o que o sistema disser da saída padrão — na dúvida, como «nao»."""
    contato_do_dono_whatsapp: str = ""
    """O chat de DESTINO COMO APARECE no WhatsApp Web: o do próprio dono («Você», «Nome (você)»)
    ou o de um 2º número dele — mensagem da própria conta pode não tocar no celular, e o dono
    testa qual toca (decisão de 2026-11-17). Vazio =
    o canal do dono desligado: a ação pedida na chamada só se confirma na sessão do PC. O agente
    do canal acha este chat lendo a lista de conversas; o nome só confere o cabeçalho antes de
    enviar (é a lista permitida desse canal, e só por esta configuração explícita)."""
    acao_expira_min: int = 10
    """Ação pedida na chamada sem confirmação pelo canal certo expira depois disto."""

    def __post_init__(self) -> None:
        faixas = {
            "duracao_para_aviso_min": (1, 120),
            "turnos": (1, 500),
            "frases_por_fala": (1, 20),
            "tentativas_de_codigo": (1, 10),
            "retencao_do_recado_dias": (0, 3650),
            "retencao_da_memoria_dias": (0, 3650),
            "acao_expira_min": (1, 120),
        }
        for nome, (minimo, maximo) in faixas.items():
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int):
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: tem de ser um número inteiro")
            if not minimo <= valor <= maximo:
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: fora de {minimo}..{maximo}")
        for nome in ("pode_dizer", "nunca_dizer", "palavra_de_coacao"):
            valor = getattr(self, nome)
            if not isinstance(valor, str) or len(valor) > TEXTO_MAXIMO:
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: texto de até {TEXTO_MAXIMO}")
        contato: object = self.contato_do_dono_whatsapp
        if not isinstance(contato, str) or len(contato) > NOME_MAXIMO or "\n" in contato:
            raise ConfiguracaoDaChamadaInvalida(
                f"contato_do_dono_whatsapp: um nome de até {NOME_MAXIMO} caracteres, numa linha"
            )
        for nome in ("lembrar_interlocutor", "chamadas_ativas"):
            valor_logico: object = getattr(self, nome)
            if not isinstance(valor_logico, bool):
                raise ConfiguracaoDaChamadaInvalida(f"{nome}: tem de ser true ou false")
        if self.fone not in FONES:
            raise ConfiguracaoDaChamadaInvalida(f"fone: um de {', '.join(FONES)}")

    @property
    def canais_de_confirmacao(self) -> tuple[str, ...]:
        """Por onde uma ação pedida na chamada se confirma: a sessão do PC sempre; o WhatsApp do
        dono só com o contato dele configurado (sem nome, o canal fica desligado)."""
        if self.contato_do_dono_whatsapp.strip():
            return (SESSAO_DO_PC, WHATSAPP_DO_DONO)
        return (SESSAO_DO_PC,)


def _migrar(dados: dict[str, Any]) -> dict[str, Any]:
    """As chaves de antes da segunda rodada de decisões: `usa_fone` vira `fone` (se o arquivo não
    tiver `fone`); `canal_de_confirmacao` sai (o canal vem do contato configurado). Tipo errado
    nelas continua recusando o arquivo."""
    novos = {k: v for k, v in dados.items() if k not in CHAVES_ANTIGAS}
    if "usa_fone" in dados:
        if not isinstance(dados["usa_fone"], bool):
            raise ConfiguracaoDaChamadaInvalida("usa_fone: tem de ser true ou false")
        novos.setdefault("fone", "sim" if dados["usa_fone"] else "nao")
    if "canal_de_confirmacao" in dados and dados["canal_de_confirmacao"] != SESSAO_DO_PC:
        raise ConfiguracaoDaChamadaInvalida(
            "canal_de_confirmacao: saiu; o canal do dono liga com contato_do_dono_whatsapp"
        )
    return novos


def de_dict(dados: dict[str, Any]) -> ConfiguracaoDaChamada:
    dados = _migrar(dados)
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
    "FONES",
    "NUNCA_DIZER_PADRAO",
    "PODE_DIZER_PADRAO",
    "SESSAO_DO_PC",
    "WHATSAPP_DO_DONO",
    "ConfiguracaoDaChamada",
    "ConfiguracaoDaChamadaInvalida",
    "gravar",
    "ler",
    "texto",
]
