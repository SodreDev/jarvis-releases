"""Presets de modelo: nome, papel, provedor, modelo e esforço, num arquivo do dono (ADR-0056).

Pedido do dono (2026-10-29): escolher modelo **e** esforço, salvar como preset numa lista e trocar
o ativo pela janela ou pela voz ("usa o preset rápido"). As regras:

- o padrão mora no repositório (`presets.toml`, ao lado deste módulo); o do dono, em
  `~/.config/jarvis/presets.toml` (a pasta do `jarvis-voz.toml`), e vence quando existe — como as
  regras do dono (ADR-0047);
- cada `[[preset]]` tem `nome`, `papel` (`cerebro`, `jev`, `visao`, `resumo`), `provedor` (um id do
  registro), `modelo` (vazio = o padrão do provedor) e `esforco` (vazio = o do provedor); a tabela
  `[ativos]` diz o preset de cada papel;
- **sem segredo**: chave nenhuma entra aqui — campo com nome de segredo ou valor com forma de chave
  recusa o arquivo inteiro; as chaves continuam no ambiente e no chaveiro;
- o cérebro ativo vazio quer dizer "o da configuração" (`s2`, `modelo_do_s2` do `jarvis-voz.toml`):
  até o dono escolher um preset, nada muda para ele. O preset que representa isso
  (`DA_CONFIGURACAO`) só existe em memória e nunca é gravado;
- escolher um preset **não liga nuvem**: um preset de provedor de nuvem desligado é recusado na
  hora de chamar, e quem liga é o dono, na janela (ADR-0017, política 2).
"""

from __future__ import annotations

import json
import re
import tomllib
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from jarvis.provedores.interface import ESFORCOS, FORMA_DO_ID, PAPEIS, Papel, limpar_texto
from jarvis.provedores.registro import CLAUDE_CLI, ECO
from jarvis.voz.chaves import (
    PARECE_CHAVE,
    SegredoNaConfiguracao,
    proibir_segredo_na_configuracao,
)
from jarvis.voz.vocabulario import pasta_do_vocabulario

if TYPE_CHECKING:
    from jarvis.voz.config import Configuracao

ARQUIVO_PADRAO: Final = Path(__file__).with_name("presets.toml")
NOME_DO_ARQUIVO: Final = "presets.toml"
MAXIMO_DE_PRESETS: Final = 40
MAXIMO_DA_NOTA: Final = 160
FORMA_DO_NOME: Final[re.Pattern[str]] = re.compile(r"[^\W_][\w .+\-]{0,39}")
"""Letras (com acento), números, espaço, `.`, `+`, `-` e `_`; até 40. É o nome que o dono fala."""
FORMA_DO_PROVEDOR: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9\-]{0,63}")
OUTRAS_CHAVES: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s=:/])(?:sk-(?:proj-|or-|ant-)?|sk_|gsk_|xi-)[A-Za-z0-9_\-]{12,}"
)
"""As formas públicas de chave dos provedores de modelo (`sk-`, `sk-proj-`, `sk-or-`, `sk-ant-`),
além das da voz (`PARECE_CHAVE`). Recusa o acidente de colar a chave no campo do modelo."""

DA_CONFIGURACAO: Final = "configuração"
"""O nome do preset que representa a escolha antiga (`s2`, `modelo_do_s2`). Só em memória."""


class PresetsInvalidos(ValueError):
    """O arquivo não é TOML, tem segredo, ou não traz nenhum `[[preset]]` que sirva."""


def normalizar(nome: str) -> str:
    """Como a voz e a tela comparam nomes: sem acento, sem caixa, `-`/`_` como espaço."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", nome) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.casefold().replace("-", " ").replace("_", " ").split())


@dataclass(frozen=True, slots=True)
class Preset:
    """Uma escolha salva: este provedor, este modelo, este esforço, para este papel."""

    nome: str
    papel: str
    provedor: str
    modelo: str = ""
    esforco: str = ""
    nota: str = ""
    da_configuracao: bool = False
    """O preset que espelha `s2`/`modelo_do_s2`: existe só em memória e não é gravado."""

    @property
    def chave(self) -> str:
        return normalizar(self.nome)

    def para_dict(self) -> dict[str, Any]:
        return {
            "nome": self.nome,
            "papel": self.papel,
            "provedor": self.provedor,
            "modelo": self.modelo,
            "esforco": self.esforco,
            "nota": self.nota,
            "daConfiguracao": self.da_configuracao,
        }


def conferir(preset: Preset) -> Preset:
    """O preset, se cada campo tem forma; senão `PresetsInvalidos` dizendo qual."""
    if not FORMA_DO_NOME.fullmatch(preset.nome):
        raise PresetsInvalidos(
            f"nome de preset {preset.nome[:40]!r} fora da forma (letras, números, espaço, . + - "
            "e _, até 40)"
        )
    if not preset.da_configuracao and normalizar(preset.nome) == normalizar(DA_CONFIGURACAO):
        raise PresetsInvalidos(
            f"«{DA_CONFIGURACAO}» é o nome reservado do cérebro do jarvis-voz.toml: escolha outro"
        )
    if preset.papel not in PAPEIS:
        raise PresetsInvalidos(
            f"o preset «{preset.nome}» tem papel {preset.papel!r}; os que existem: "
            f"{', '.join(PAPEIS)}"
        )
    if not FORMA_DO_PROVEDOR.fullmatch(preset.provedor):
        raise PresetsInvalidos(f"o preset «{preset.nome}» tem provedor fora da forma")
    if preset.modelo and not FORMA_DO_ID.fullmatch(preset.modelo):
        raise PresetsInvalidos(
            f"o preset «{preset.nome}» tem modelo fora da forma de um id (sem espaço nem aspas)"
        )
    if preset.esforco and preset.esforco not in ESFORCOS:
        raise PresetsInvalidos(
            f"o preset «{preset.nome}» tem esforço {preset.esforco!r}; os que existem: "
            f"{', '.join(ESFORCOS)}"
        )
    return replace(preset, nota=limpar_texto(preset.nota, limite=MAXIMO_DA_NOTA))


@dataclass(frozen=True, slots=True)
class Presets:
    """A lista de presets e o ativo de cada papel."""

    presets: tuple[Preset, ...]
    ativos: Mapping[str, str] = field(default_factory=dict)
    """Papel → nome do preset ativo. Ausente ou vazio = nenhum (no cérebro: o da configuração)."""
    origem: str = "padrao"
    """`padrao` ou o caminho do arquivo do dono."""
    avisos: tuple[str, ...] = ()

    def por_nome(self, nome: str) -> Preset | None:
        chave = normalizar(nome)
        return next((p for p in self.presets if p.chave == chave), None)

    def do_papel(self, papel: str) -> tuple[Preset, ...]:
        return tuple(p for p in self.presets if p.papel == papel)

    def ativo(self, papel: str) -> Preset | None:
        nome = self.ativos.get(papel, "")
        preset = self.por_nome(nome) if nome else None
        return preset if preset is not None and preset.papel == papel else None

    def com_ativo(self, papel: str, nome: str) -> Presets:
        """Este preset passa a ser o ativo do papel dele. Vazio desliga o papel."""
        if not nome:
            return replace(self, ativos={**self.ativos, papel: ""})
        preset = self.por_nome(nome)
        if preset is None:
            raise PresetsInvalidos(f"não há preset chamado «{nome}»")
        if preset.papel != papel:
            raise PresetsInvalidos(f"o preset «{preset.nome}» é de {preset.papel}, não de {papel}")
        return replace(self, ativos={**self.ativos, papel: preset.nome})

    def com_preset(self, preset: Preset) -> Presets:
        """Acrescenta, ou troca o de mesmo nome. Trocar o papel de um ativo o desliga."""
        novo = conferir(preset)
        outros = [p for p in self.presets if p.chave != novo.chave]
        if sum(not p.da_configuracao for p in outros) >= MAXIMO_DE_PRESETS:
            raise PresetsInvalidos(f"já há {MAXIMO_DE_PRESETS} presets: apague um antes")
        ativos = {
            papel: nome
            for papel, nome in self.ativos.items()
            if normalizar(nome) != novo.chave or papel == novo.papel
        }
        return replace(self, presets=(*outros, novo), ativos=ativos)

    def sem_preset(self, nome: str) -> Presets:
        chave = normalizar(nome)
        return replace(
            self,
            presets=tuple(p for p in self.presets if p.chave != chave),
            ativos={papel: n for papel, n in self.ativos.items() if normalizar(n) != chave},
        )

    def para_toml(self) -> str:
        """O arquivo do dono. O preset da configuração fica de fora: vem do `jarvis-voz.toml`."""
        linhas = [
            "# Presets de modelo do Jarvis (ADR-0056). Sem segredo: as chaves ficam no ambiente e",
            "# no chaveiro. Papéis: cerebro, jev, visao, resumo. Esforços: "
            + ", ".join(ESFORCOS)
            + ".",
            "# Cérebro ativo vazio = o da configuração (s2 e modelo_do_s2 do jarvis-voz.toml).",
            "",
            "versao = 1",
            "",
            "[ativos]",
        ]
        for papel in PAPEIS:
            nome = self.ativos.get(papel, "")
            preset = self.por_nome(nome) if nome else None
            gravado = "" if preset is None or preset.da_configuracao else preset.nome
            linhas.append(f"{papel} = {_aspas(gravado)}")
        for preset in self.presets:
            if preset.da_configuracao:
                continue
            linhas += [
                "",
                "[[preset]]",
                f"nome = {_aspas(preset.nome)}",
                f"papel = {_aspas(preset.papel)}",
                f"provedor = {_aspas(preset.provedor)}",
                f"modelo = {_aspas(preset.modelo)}",
                f"esforco = {_aspas(preset.esforco)}",
            ]
            if preset.nota:
                linhas.append(f"nota = {_aspas(preset.nota)}")
        return "\n".join(linhas) + "\n"

    def para_dict(self) -> dict[str, Any]:
        return {
            "presets": [p.para_dict() for p in self.presets],
            "ativos": {papel: self.ativos.get(papel, "") for papel in PAPEIS},
            "origem": self.origem,
            "avisos": list(self.avisos),
        }


def _aspas(valor: str) -> str:
    """String básica de TOML: a do JSON serve (mesmos escapes, `\\uXXXX` incluído)."""
    return json.dumps(valor, ensure_ascii=False)


def _sem_segredo(dados: Mapping[str, Any], arquivo: str) -> None:
    try:
        proibir_segredo_na_configuracao(dados, arquivo=arquivo)
        for bruto in dados.get("preset", []):
            if isinstance(bruto, Mapping):
                proibir_segredo_na_configuracao(bruto, arquivo=arquivo)
                for valor in bruto.values():
                    if isinstance(valor, str) and (
                        PARECE_CHAVE.search(valor) or OUTRAS_CHAVES.search(valor)
                    ):
                        raise SegredoNaConfiguracao("valor com a forma de chave de API")
    except SegredoNaConfiguracao:
        # A mensagem é nossa (sem repetir o valor): vale na leitura e antes de gravar.
        raise PresetsInvalidos(
            f"{arquivo}: há campo com nome de segredo ou valor com a forma de chave de API — "
            "chave não entra em presets; ela fica no ambiente ou no chaveiro"
        ) from None


def de_dados(dados: Mapping[str, Any], *, origem: str) -> Presets:
    """Os presets de um TOML já lido. Preset sem forma fica de fora, com aviso."""
    _sem_segredo(dados, origem)
    brutos = dados.get("preset")
    if not isinstance(brutos, list):
        raise PresetsInvalidos(f"{origem}: falta a lista [[preset]]")
    presets: list[Preset] = []
    avisos: list[str] = []
    for bruto in brutos:
        if not isinstance(bruto, Mapping):
            continue
        try:
            preset = conferir(
                Preset(
                    nome=str(bruto.get("nome", "")).strip(),
                    papel=str(bruto.get("papel", "")).strip(),
                    provedor=str(bruto.get("provedor", "")).strip(),
                    modelo=str(bruto.get("modelo", "")).strip(),
                    esforco=str(bruto.get("esforco", "")).strip(),
                    nota=str(bruto.get("nota", "")),
                )
            )
        except PresetsInvalidos as erro:
            avisos.append(f"ficou de fora: {erro}")
            continue
        if any(p.chave == preset.chave for p in presets):
            avisos.append(f"o nome «{preset.nome}» repete: valeu o primeiro")
            continue
        if len(presets) == MAXIMO_DE_PRESETS:
            avisos.append(f"mais de {MAXIMO_DE_PRESETS} presets: os de depois ficaram de fora")
            break
        presets.append(preset)
    if not presets:
        raise PresetsInvalidos(f"{origem}: nenhum preset com nome, papel e provedor")
    ativos_brutos = dados.get("ativos", {})
    ativos: dict[str, str] = {}
    if isinstance(ativos_brutos, Mapping):
        for papel in PAPEIS:
            nome = str(ativos_brutos.get(papel, "")).strip()
            escolhido = next((p for p in presets if p.chave == normalizar(nome)), None)
            if nome and (escolhido is None or escolhido.papel != papel):
                avisos.append(f"o ativo de {papel} («{nome}») não é um preset desse papel")
                continue
            ativos[papel] = escolhido.nome if escolhido is not None else ""
    return Presets(tuple(presets), ativos, origem, tuple(avisos))


def ler(arquivo: Path) -> Presets:
    try:
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as erro:
        raise PresetsInvalidos(f"{arquivo.name}: {erro}") from None
    return de_dados(dados, origem=str(arquivo))


def padrao() -> Presets:
    """Os presets do repositório (sempre válidos: o teste confere)."""
    return replace(ler(ARQUIVO_PADRAO), origem="padrao")


def arquivo_do_dono(ambiente: Mapping[str, str] | None = None) -> Path | None:
    pasta = pasta_do_vocabulario(ambiente)
    return pasta / NOME_DO_ARQUIVO if pasta is not None else None


def preset_da_configuracao(configuracao: Configuracao) -> Preset:
    """A escolha antiga, como preset: `s2 = "eco"` é o eco; `s2 = "claude"`, a CLI do Claude com
    o `modelo_do_s2` (vazio = o padrão da CLI) e o esforço por modo de sempre."""
    if configuracao.s2 == "claude":
        return Preset(
            DA_CONFIGURACAO,
            Papel.CEREBRO,
            CLAUDE_CLI,
            modelo=configuracao.modelo_do_s2
            if FORMA_DO_ID.fullmatch(configuracao.modelo_do_s2)
            else "",
            nota="s2 e modelo_do_s2 do jarvis-voz.toml",
            da_configuracao=True,
        )
    return Preset(
        DA_CONFIGURACAO, Papel.CEREBRO, ECO, nota="s2 do jarvis-voz.toml", da_configuracao=True
    )


def com_a_configuracao(presets: Presets, configuracao: Configuracao | None) -> Presets:
    """Sem cérebro ativo, vale o da configuração: o preset dela entra (em memória) e fica ativo."""
    if configuracao is None or presets.ativo(Papel.CEREBRO) is not None:
        return presets
    legado = preset_da_configuracao(configuracao)
    outros = tuple(p for p in presets.presets if p.chave != legado.chave)
    return replace(
        presets,
        presets=(legado, *outros),
        ativos={**presets.ativos, Papel.CEREBRO.value: legado.nome},
    )


def do_dono(
    configuracao: Configuracao | None = None, ambiente: Mapping[str, str] | None = None
) -> Presets:
    """Os presets que valem: os do dono, se o arquivo existe e serve; senão o padrão (com o
    aviso, quando o do dono não serviu). Sem cérebro ativo, entra o da configuração."""
    arquivo = arquivo_do_dono(ambiente)
    return com_a_configuracao(na_pasta(arquivo.parent) if arquivo else padrao(), configuracao)


def na_pasta(pasta: Path) -> Presets:
    arquivo = pasta / NOME_DO_ARQUIVO
    if not arquivo.is_file():
        return padrao()
    try:
        return ler(arquivo)
    except PresetsInvalidos as erro:
        base = padrao()
        return replace(base, avisos=(f"o arquivo do dono não serviu ({erro})",))


def gravar(presets: Presets, arquivo: Path) -> Path:
    """Grava o arquivo do dono por inteiro (troca atômica) e devolve o caminho. O texto passa pela
    mesma leitura antes de ir ao disco: o que a tela ou a voz gravam é o que se lê depois."""
    texto = presets.para_toml()
    de_dados(tomllib.loads(texto), origem=str(arquivo))
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".toml.tmp")
    temporario.write_text(texto, encoding="utf-8")
    temporario.replace(arquivo)
    return arquivo


@dataclass(slots=True)
class FonteDePresets:
    """Os presets que valem **agora**, relidos quando o arquivo do dono muda.

    A janela e a voz gravam o arquivo; o roteador do cérebro lê daqui a cada pedido. A releitura
    custa um `stat` quando nada mudou.
    """

    ambiente: Mapping[str, str] | None = None
    configuracao: Configuracao | None = None
    pasta: Path | None = None
    """A pasta do arquivo do dono. `None` = a do `jarvis-voz.toml` deste ambiente."""
    nuvem: Callable[[], tuple[frozenset[str], frozenset[str]]] | None = field(
        default=None, repr=False
    )
    """A nuvem que o dono ligou **agora** — `(ligados, sem_termos)` da configuração viva da janela.
    O cérebro e a troca pela voz leem daqui a cada pedido: antes, ligar o Groq na janela valia só
    para a janela, e a conversa aberta seguia recusando com «está desligado» (dono, 2026-10-30).
    `None` = sem janela (o terminal): vale o que a conversa leu ao abrir."""
    _marca: tuple[int, int] | None = field(default=None, repr=False)
    _presets: Presets | None = field(default=None, repr=False)

    @property
    def arquivo(self) -> Path | None:
        if self.pasta is not None:
            return self.pasta / NOME_DO_ARQUIVO
        return arquivo_do_dono(self.ambiente)

    def atuais(self) -> Presets:
        arquivo = self.arquivo
        try:
            estado = arquivo.stat() if arquivo is not None else None
            marca = (estado.st_mtime_ns, estado.st_size) if estado is not None else None
        except OSError:
            marca = None
        if self._presets is None or marca != self._marca:
            base = na_pasta(arquivo.parent) if arquivo is not None else padrao()
            self._presets = com_a_configuracao(base, self.configuracao)
            self._marca = marca
        return self._presets

    def trocar_configuracao(self, configuracao: Configuracao | None) -> None:
        self.configuracao = configuracao
        self._presets = None

    def gravar(self, presets: Presets) -> Path:
        """Grava o arquivo do dono — menos quando ele existe e não serve: aí os presets de agora
        são o padrão, e gravar por cima apagaria o que ele escreveu à mão (vale para a janela e
        para a voz)."""
        arquivo = self.arquivo
        if arquivo is None:
            raise PresetsInvalidos("este ambiente não tem pasta de configuração para gravar")
        if arquivo.is_file():
            try:
                ler(arquivo)
            except PresetsInvalidos as erro:
                raise PresetsInvalidos(
                    f"o seu {arquivo.name} não serviu ({erro}): conserte-o ou apague-o — gravar "
                    "agora por cima apagaria o que está nele"
                ) from None
        caminho = gravar(presets, arquivo)
        self._presets = None
        return caminho


@dataclass(slots=True)
class TrocaPorVoz:
    """O corpo da `modelo.preset` (ADR-0056): ativa um preset que o dono nomeou, no papel dele,
    gravando o arquivo do dono. Não cria preset e **não liga nuvem**: preset de provedor
    desligado volta como erro, com a frase de onde se liga."""

    fonte: FonteDePresets
    ligado: Callable[[str], bool]
    """O provedor pode chamar agora? (local, ou de nuvem que o dono ligou)."""

    def usar(self, nome: str) -> dict[str, str]:
        presets = self.fonte.atuais()
        preset = presets.por_nome(nome)
        if preset is None or preset.da_configuracao:
            de_cerebro = [p for p in presets.do_papel(Papel.CEREBRO) if not p.da_configuracao]
            raise ValueError(
                f"não há preset chamado «{nome}». Os de cérebro: {nomes_para_falar(de_cerebro)}"
            )
        ligado_agora = self.fonte.nuvem is not None and preset.provedor in self.fonte.nuvem()[0]
        if not ligado_agora and not self.ligado(preset.provedor):
            raise ValueError(
                f"o preset «{preset.nome}» usa {preset.provedor}, que é de nuvem e está desligado: "
                "ligue o provedor na janela (Configuração → resposta), onde está o aviso do que sai"
            )
        anterior = presets.ativo(preset.papel)
        guardado = "" if anterior is None or anterior.da_configuracao else anterior.nome
        self.fonte.gravar(presets.com_ativo(preset.papel, preset.nome))
        return {
            "preset": preset.nome,
            "papel": str(preset.papel),
            "provedor": preset.provedor,
            "modelo": preset.modelo,
            "desfazer": f"{preset.papel}={guardado}",
        }

    def voltar(self, alvo: str) -> None:
        papel, _, nome = alvo.partition("=")
        if papel not in PAPEIS:
            raise ValueError(f"desfazer de preset sem papel válido: {alvo!r}")
        presets = self.fonte.atuais()
        self.fonte.gravar(presets.com_ativo(papel, nome if presets.por_nome(nome) else ""))


def nomes_para_falar(presets: Sequence[Preset]) -> str:
    """ "rápido, claude e visão" — para a resposta falada de quem não achou o preset."""
    nomes = [p.nome for p in presets]
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


__all__ = [
    "ARQUIVO_PADRAO",
    "DA_CONFIGURACAO",
    "FonteDePresets",
    "Preset",
    "Presets",
    "PresetsInvalidos",
    "TrocaPorVoz",
    "arquivo_do_dono",
    "com_a_configuracao",
    "conferir",
    "de_dados",
    "do_dono",
    "gravar",
    "ler",
    "na_pasta",
    "nomes_para_falar",
    "normalizar",
    "padrao",
    "preset_da_configuracao",
]
