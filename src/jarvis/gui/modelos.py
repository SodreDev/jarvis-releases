"""Presets de modelo na janela — a ponta Qt de `jarvis.provedores` (ADR-0056).

Fina como a ponte (ADR-0019): lê os presets que valem agora (`FonteDePresets`), pergunta ao
registro e ao catálogo (`Provedores`) o que cada provedor oferece e **grava o arquivo do dono na
hora** — o mesmo arquivo que a voz (`modelo.preset`) e o roteador do cérebro leem. Três regras:

1. **listar não trava a tela.** Abrir um provedor mostra a lista sem rede (a guardada, senão a do
   registro). A lista de agora (`buscarModelos`) e o que falta para ele chamar (a `prontidao` das
   CLIs roda um processo; a chave pode vir do chaveiro) vão numa thread e voltam por sinal, que o
   Qt entrega na thread da janela.
2. **escolher não liga nuvem.** Salvar ou ativar um preset de provedor desligado só avisa; ligar é
   o botão depois do aviso montado do registro (ADR-0017, política 2), e vale nesta sessão até o
   dono salvar a configuração.
3. **erro vira frase.** Preset fora da forma, valor com forma de chave, arquivo do dono que não
   serviu: volta como texto (o retorno do slot e `aviso`), nunca como exceção no QML.

O que vem do provedor (id, nome, preço) é dado de terceiros: chega limpo do catálogo e a tela o
mostra como texto puro.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import Property, QObject, Signal, Slot

from jarvis.provedores.catalogo import Listagem, Origem
from jarvis.provedores.interface import ESFORCOS, PAPEIS, Capacidades, Modelo, Papel, id_valido
from jarvis.provedores.nucleo import Provedores
from jarvis.provedores.presets import (
    DA_CONFIGURACAO,
    OUTRAS_CHAVES,
    FonteDePresets,
    Preset,
    Presets,
    PresetsInvalidos,
    normalizar,
    preset_da_configuracao,
)
from jarvis.provedores.registro import ECO
from jarvis.voz.chaves import PARECE_CHAVE, Chave
from jarvis.voz.config import Configuracao
from jarvis.voz.registro import Motor, MotorRecusado, motores_de

DE_DECISAO: Final = "decisao"
"""O papel, no registro de motores, de quem atende o preset `jev`: o Jev é um classificador
(ADR-0029) de `licenses/motores.toml`, não um provedor de conversa."""
PAPEIS_DE_CONVERSA: Final[tuple[str, ...]] = (
    Papel.CEREBRO.value,
    Papel.VISAO.value,
    Papel.RESUMO.value,
)
NOME_DO_PAPEL: Final[Mapping[str, str]] = {
    Papel.CEREBRO.value: "cérebro",
    Papel.JEV.value: "jev",
    Papel.VISAO.value: "visão",
    Papel.RESUMO.value: "resumo",
}
NAO_INFORMADO: Final = "não informado"
"""Capacidade `None`: o provedor e o registro não disseram — não é "não" (ADR-0056, seção 1)."""


def nome_curto(motor: Motor) -> str:
    """O serviço sem o parêntese: "OpenAI (API)" → "OpenAI"."""
    return motor.servico.split(" (")[0].strip() or motor.id


def apelido(motor: Motor) -> str:
    """O id sem o prefixo do papel (`conversa-codex-cli` → `codex-cli`): é o que separa a API da
    OpenAI da CLI do Codex, que têm o mesmo serviço."""
    return motor.id.partition("-")[2] or motor.id


def _tokens(quantidade: int) -> str:
    if quantidade >= 1_000_000:
        return f"{quantidade / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "M"
    if quantidade >= 1000:
        return f"{round(quantidade / 1000)}k"
    return str(quantidade)


def _dolares(valor: float) -> str:
    texto = f"{valor:.2f}" if valor == 0 or valor >= 0.1 else f"{valor:.6f}".rstrip("0")
    return (texto + "0" if texto.endswith(".") else texto).replace(".", ",")


def _preco(entrada: float | None, saida: float | None) -> str:
    if entrada is None and saida is None:
        return f"preço: {NAO_INFORMADO}"
    if entrada == 0 and saida == 0:
        return "grátis"
    lados = [_dolares(valor) if valor is not None else NAO_INFORMADO for valor in (entrada, saida)]
    return f"US$ {lados[0]}/{lados[1]} por milhão"


def resumo_das_capacidades(capacidades: Capacidades) -> str:
    """Uma linha para a tela: "vê imagem · ferramentas · 200k contexto · US$ 1,50/6,00 por
    milhão". Os esforços ficam de fora: eles são os botões do passo seguinte."""
    c = capacidades
    if c.visao is None:
        visao = f"visão: {NAO_INFORMADO}"
    else:
        visao = "vê imagem" if c.visao else "não vê imagem"
    if c.ferramentas is None:
        ferramentas = f"ferramentas: {NAO_INFORMADO}"
    else:
        ferramentas = "ferramentas" if c.ferramentas else "sem ferramentas"
    partes = [
        visao,
        ferramentas,
        f"{_tokens(c.contexto)} contexto"
        if c.contexto is not None
        else f"contexto: {NAO_INFORMADO}",
    ]
    if c.saida_maxima is not None:
        partes.append(f"saída até {_tokens(c.saida_maxima)}")
    partes.append(_preco(c.preco_entrada, c.preco_saida))
    if c.latencia:
        partes.append(f"latência {c.latencia}")
    return " · ".join(partes)


def _quando(iso: str) -> str:
    """`2026-10-29T14:03:00Z` → `2026-10-29 14:03 UTC`; a data do registro passa como está."""
    if "T" in iso and iso.endswith("Z"):
        data, _, hora = iso[:-1].partition("T")
        return f"{data} {hora[:5]} UTC"
    return iso


def _frase_da_lista(listagem: Listagem) -> str:
    quantos = len(listagem.modelos)
    modelos = "1 modelo" if quantos == 1 else f"{quantos} modelos"
    quando = _quando(listagem.lida_em)
    de_onde = {
        Origem.PROVEDOR: f"lista do provedor, lida em {quando}",
        Origem.CACHE: f"lista guardada, lida em {quando}",
        Origem.REGISTRO: f"lista do registro, conferida em {quando}",
    }[listagem.origem]
    return f"{modelos} · {de_onde}"


def da_decisao(motor: Motor) -> bool:
    return motor.papel == DE_DECISAO


def papeis_de(motor: Motor) -> tuple[str, ...]:
    """Para que o provedor serve: o Jev só para `jev`; os de conversa, para o resto."""
    return (Papel.JEV.value,) if da_decisao(motor) else PAPEIS_DE_CONVERSA


def esta_ligado(motor: Motor, provedores: Provedores) -> bool:
    """Pode chamar agora: local, ou de nuvem que o dono ligou (`nuvem_ligada`, e a CLI do Claude
    com `s2 = "claude"`). Vale para o Jev, que é do registro de motores."""
    return not motor.na_nuvem or motor.ligado or motor.id in provedores.ligados


def lista_sem_rede(motor: Motor, provedores: Provedores) -> Listagem:
    """A lista sem abrir socket. A do Jev é a do registro de motores: o modelo dele é fixado
    porque os limiares do detector foram calibrados nele (ADR-0029)."""
    if da_decisao(motor):
        return Listagem(
            motor.id,
            tuple(Modelo(id=m) for m in motor.modelos_permitidos if id_valido(m)),
            Origem.REGISTRO,
            motor.data_dos_modelos or motor.data_de_acesso,
        )
    return provedores.sem_rede(motor.id)


def lista_para_a_tela(motor: Motor, listagem: Listagem) -> dict[str, Any]:
    """`Listagem.para_dict`, com o que a tela escreve pronto: o nome do provedor, a frase de onde
    a lista veio, o modelo padrão do registro e a linha de capacidades de cada modelo."""
    dados = listagem.para_dict()
    dados["modelos"] = [
        {
            **modelo.para_dict(),
            "resumo": "classificador por perguntas fechadas (ADR-0029): sem esforço"
            if da_decisao(motor)
            else resumo_das_capacidades(modelo.capacidades),
        }
        for modelo in listagem.modelos
    ]
    dados["nome"] = nome_curto(motor)
    dados["padrao"] = motor.modelo
    dados["frase"] = _frase_da_lista(listagem)
    return dados


class PonteDeModelos(QObject):
    """O que o QML lê (`provedores`, `presets`, `ativos`, `listagem`…) e o que ele pede."""

    mudou = Signal()
    listagemChegou = Signal(str, object, str)
    """(provedor, lista para a tela ou `None`, frase): vem da thread da busca; o Qt entrega na da
    janela."""
    prontidaoChegou = Signal(str, str)
    """(provedor, o que falta para ele chamar): vem da thread que pergunta à CLI e ao chaveiro."""

    def __init__(
        self,
        *,
        fonte: FonteDePresets,
        provedores: Callable[[], Provedores],
        ligar_nuvem: Callable[[str, bool], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._fonte = fonte
        self._provedores = provedores
        """Monta os `Provedores` da configuração **viva**: a nuvem que o dono acabou de ligar já
        conta no `ligado` seguinte."""
        self._ligar_nuvem = ligar_nuvem
        """O interruptor da janela (`Ponte.ligarNuvem`): muda `nuvem_ligada` nesta sessão; o
        "salvar configuração" é que grava o arquivo."""
        self._registrados: tuple[Motor, ...] | None = None
        self._aberto = ""
        self._listagem: dict[str, Any] = {}
        self._carregando = False
        self._falta = ""
        self._aviso = ""
        self.listagemChegou.connect(self._chegou_a_lista)
        self.prontidaoChegou.connect(self._chegou_a_prontidao)

    @property
    def fonte(self) -> FonteDePresets:
        """A fonte de presets da janela — a ponte a passa à sessão, e o cérebro lê dela."""
        return self._fonte

    @classmethod
    def da_janela(
        cls,
        *,
        obter: Callable[[], Configuracao],
        raiz: Path,
        ambiente: Mapping[str, str] | None,
        pasta: Path | None,
        ligar_nuvem: Callable[[str, bool], None],
        parent: QObject | None = None,
    ) -> PonteDeModelos:
        """Como a janela monta: os presets do arquivo do dono (`pasta`; `None` = a do
        `jarvis-voz.toml` deste ambiente, a mesma que o laço lê) e os provedores da configuração
        viva, com as CLIs na pasta de conversa do laço (`raiz/conversa`, ADR-0018)."""
        return cls(
            fonte=FonteDePresets(ambiente=ambiente, configuracao=obter(), pasta=pasta),
            provedores=lambda: Provedores.da_configuracao(
                obter(), pasta_de_trabalho=raiz / "conversa", ambiente=ambiente
            ),
            ligar_nuvem=ligar_nuvem,
            parent=parent,
        )

    # --- o registro --------------------------------------------------------------------------
    def _motores(self) -> tuple[Motor, ...]:
        """Os provedores de conversa, na ordem do registro, e os de decisão (o Jev). O registro
        não muda com a janela aberta: é lido uma vez."""
        if self._registrados is None:
            self._registrados = (*self._provedores().registrados(), *motores_de(DE_DECISAO))
        return self._registrados

    def _motor(self, identificador: str) -> Motor | None:
        return next((m for m in self._motores() if m.id == identificador), None)

    def _atuais(self) -> Presets | None:
        try:
            return self._fonte.atuais()
        except (PresetsInvalidos, OSError):
            return None

    def _para_gravar(self) -> Presets:
        """Os presets de agora, para mudar e gravar. Se o arquivo do dono existe e não serviu, a
        janela não grava por cima: o que ele escreveu à mão se perderia."""
        atuais = self._fonte.atuais()
        arquivo = self._fonte.arquivo
        if arquivo is not None and arquivo.is_file() and atuais.origem == "padrao":
            raise PresetsInvalidos(
                f"o arquivo {arquivo} não serviu: conserte-o ou apague-o — gravar agora por cima "
                "apagaria o que está nele"
            )
        return atuais

    def _com_a_configuracao(self, atuais: Presets) -> tuple[Preset, ...]:
        """A lista da tela. O cérebro sempre tem «configuração» (o `s2` do `jarvis-voz.toml`),
        para o dono voltar a ela mesmo com outro preset ativo — o arquivo só a traz quando
        nenhum está. Ela existe só em memória: gravar a deixa de fora."""
        if any(p.da_configuracao for p in atuais.presets):
            return atuais.presets
        configuracao = self._fonte.configuracao
        legado = (
            preset_da_configuracao(configuracao)
            if configuracao is not None
            else Preset(DA_CONFIGURACAO, Papel.CEREBRO.value, ECO, da_configuracao=True)
        )
        return (legado, *(p for p in atuais.presets if p.chave != legado.chave))

    @staticmethod
    def _ativos_de(atuais: Presets) -> dict[str, str]:
        ativos = {papel: atuais.ativos.get(papel, "") for papel in PAPEIS}
        ativos[Papel.CEREBRO.value] = ativos[Papel.CEREBRO.value] or DA_CONFIGURACAO
        return ativos

    def _resumo_do_preset(self, preset: Preset, motor: Motor | None) -> str:
        partes = [
            apelido(motor) if motor is not None else preset.provedor,
            preset.modelo or "modelo padrão",
        ]
        if motor is None or not da_decisao(motor):  # o Jev classifica: não tem esforço
            partes.append(f"esforço {preset.esforco}" if preset.esforco else "esforço do provedor")
        return " · ".join(partes) + (f" — {preset.nota}" if preset.nota else "")

    def _avisar(self, frase: str) -> str:
        self._aviso = frase
        self.mudou.emit()
        return frase

    # --- o que a tela lê -----------------------------------------------------------------------
    @Property(list, notify=mudou)
    def provedores(self) -> list[dict[str, Any]]:
        """Os provedores de conversa e o Jev: nome, onde roda, se está ligado e o aviso de nuvem
        montado do registro (ADR-0017, política 3)."""
        provedores = self._provedores()
        return [
            {
                "id": motor.id,
                "nome": nome_curto(motor),
                "apelido": apelido(motor),
                "servico": motor.servico,
                "onde": "nuvem" if motor.na_nuvem else "local",
                "ligado": esta_ligado(motor, provedores),
                "aviso": motor.frase_de_aviso,
                "variavelDaChave": motor.variavel_da_chave,
                "papeis": list(papeis_de(motor)),
                "listaAoVivo": not da_decisao(motor),
            }
            for motor in self._motores()
        ]

    @Property(list, notify=mudou)
    def presets(self) -> list[dict[str, Any]]:
        atuais = self._atuais()
        if atuais is None:
            return []
        provedores = self._provedores()
        ativos = self._ativos_de(atuais)
        linhas: list[dict[str, Any]] = []
        for preset in self._com_a_configuracao(atuais):
            motor = self._motor(preset.provedor)
            papel = str(preset.papel)
            linhas.append(
                {
                    **preset.para_dict(),
                    "papel": papel,
                    "ativo": ativos.get(papel) == preset.nome,
                    "ligado": motor is not None and esta_ligado(motor, provedores),
                    "resumo": self._resumo_do_preset(preset, motor),
                }
            )
        return linhas

    @Property(dict, notify=mudou)
    def ativos(self) -> dict[str, str]:
        """Papel → nome do preset ativo. O cérebro sem preset é «configuração»; os outros papéis
        sem preset ficam vazios."""
        atuais = self._atuais()
        return self._ativos_de(atuais) if atuais is not None else {}

    @Property(list, constant=True)
    def papeis(self) -> list[str]:
        return list(PAPEIS)

    @Property(list, constant=True)
    def esforcos(self) -> list[str]:
        return list(ESFORCOS)

    @Property(dict, notify=mudou)
    def listagem(self) -> dict[str, Any]:
        """A lista do provedor aberto (vazia quando nenhum está), com de onde ela veio."""
        return self._listagem

    @Property(bool, notify=mudou)
    def carregando(self) -> bool:
        return self._carregando

    @Property(str, notify=mudou)
    def falta(self) -> str:
        """O que falta para o provedor aberto chamar agora (a CLI, o login, a chave), ou vazio."""
        return self._falta

    @Property(str, notify=mudou)
    def aviso(self) -> str:
        return self._aviso

    @Property(dict, notify=mudou)
    def arquivo(self) -> dict[str, Any]:
        """Onde os presets são gravados e o que a leitura avisou (arquivo do dono que não serviu,
        preset que ficou de fora)."""
        caminho = self._fonte.arquivo
        atuais = self._atuais()
        return {
            "caminho": str(caminho) if caminho is not None else "",
            "doDono": atuais is not None and atuais.origem != "padrao",
            "avisos": list(atuais.avisos) if atuais is not None else ["os presets não abriram"],
        }

    # --- o que a tela pede ---------------------------------------------------------------------
    @Slot(str)
    def abrirProvedor(self, identificador: str) -> None:
        """Mostra os modelos de um provedor **sem rede** (a lista guardada, senão a do registro) e
        pergunta, numa thread, o que falta para ele chamar. Vazio fecha."""
        self._aberto, self._listagem, self._falta = "", {}, ""
        motor = self._motor(identificador) if identificador else None
        if identificador and motor is None:
            self._avisar(f"não deu: o provedor {identificador[:64]!r} não está no registro")
            return
        if motor is not None:
            self._aberto = motor.id
            provedores = self._provedores()
            try:
                self._listagem = lista_para_a_tela(motor, lista_sem_rede(motor, provedores))
            except (MotorRecusado, OSError, ValueError) as erro:
                self._listagem = {
                    "provedor": motor.id,
                    "nome": nome_curto(motor),
                    "origem": "",
                    "lidaEm": "",
                    "aviso": f"a lista não abriu: {erro}",
                    "modelos": [],
                    "padrao": motor.modelo,
                    "frase": "sem lista",
                }
            self._sondar(motor, provedores)
        self.mudou.emit()

    def _sondar(self, motor: Motor, provedores: Provedores) -> None:
        """O que falta para o provedor chamar: a CLI e o login (`prontidao`, que roda um
        processo) e a chave (que pode vir do chaveiro). Numa thread: nada disso trava a tela."""
        identificador, variavel = motor.id, motor.variavel_da_chave
        de_conversa = not da_decisao(motor)

        def trabalhar() -> None:
            falta = ""
            try:
                if de_conversa:
                    verificar = getattr(provedores.abrir(identificador), "prontidao", None)
                    if callable(verificar):
                        falta = str(verificar() or "")
                if (
                    not falta
                    and variavel
                    and not Chave.presente(variavel, ambiente=provedores.ambiente)
                ):
                    falta = f"falta a chave {variavel}: guarde-a em «chaves de api», nesta tela"
            except Exception as erro:  # a frase do provedor, qualquer que seja, vai à tela
                falta = str(erro)
            self.prontidaoChegou.emit(identificador, falta)

        threading.Thread(target=trabalhar, name="jarvis-prontidao", daemon=True).start()

    def _chegou_a_prontidao(self, identificador: str, falta: str) -> None:
        if identificador == self._aberto:
            self._falta = falta
            self.mudou.emit()

    @Slot(str)
    def buscarModelos(self, identificador: str) -> None:
        """A lista **de agora**, do endpoint ou do comando do provedor, numa thread (é rede ou
        processo). Não passa pelo interruptor da nuvem: listar não leva nada do dono, só a chave
        no cabeçalho (ADR-0056, seção 3). Falhando, vale a guardada ou a do registro, com o
        aviso de por quê."""
        motor = self._motor(identificador)
        if motor is None:
            self._avisar(f"não deu: o provedor {identificador[:64]!r} não está no registro")
            return
        if da_decisao(motor):
            self._avisar(
                f"{nome_curto(motor)} não tem lista para buscar: o modelo é o do registro, onde "
                "os limiares do detector foram calibrados (ADR-0029)"
            )
            return
        if self._carregando:
            return
        self._carregando = True
        nome = nome_curto(motor)
        self._avisar(f"buscando a lista de {nome}…")
        provedores = self._provedores()

        def trabalhar() -> None:
            try:
                listagem = provedores.listar(identificador, forcar=True)
                dados = lista_para_a_tela(motor, listagem)
            except Exception as erro:  # sem a lista, a frase do motivo; nunca a thread morta
                self.listagemChegou.emit(identificador, None, f"não deu: {erro}")
                return
            quantos = len(listagem.modelos)
            if listagem.origem is Origem.PROVEDOR:
                frase = f"{quantos} modelo(s) de {nome}, lidos agora do provedor"
            else:
                frase = listagem.aviso or dados["frase"]
            self.listagemChegou.emit(identificador, dados, frase)

        threading.Thread(target=trabalhar, name="jarvis-modelos", daemon=True).start()

    def _chegou_a_lista(self, identificador: str, dados: object, frase: str) -> None:
        self._carregando = False
        if identificador == self._aberto:
            if isinstance(dados, dict):
                self._listagem = dados
            self._aviso = frase
        self.mudou.emit()

    @Slot(str, str, result=list)
    def esforcosDe(self, provedor: str, modelo: str) -> list[str]:
        """Os esforços que o modelo aceita, quando se sabe; senão todos (`None` não é "nenhum").
        Modelo vazio = o padrão do registro. O Jev não tem esforço."""
        motor = self._motor(provedor)
        if motor is None:
            return list(ESFORCOS)
        if da_decisao(motor):
            return []
        escolhido = modelo or motor.modelo
        conhecido: object = None
        if self._listagem.get("provedor") == provedor:
            achado = next(
                (m for m in self._listagem.get("modelos", []) if m.get("id") == escolhido), None
            )
            if achado is not None:
                conhecido = achado["capacidades"].get("esforcos")
        if conhecido is None and escolhido:
            try:
                conhecido = self._provedores().capacidades(provedor, escolhido).esforcos
            except (MotorRecusado, OSError, ValueError):
                conhecido = None
        if not isinstance(conhecido, list | tuple):
            return list(ESFORCOS)
        return [e for e in ESFORCOS if e in conhecido]

    @Slot(str, result=str)
    def nomeExistente(self, nome: str) -> str:
        """O nome de um preset que já existe com este nome (sem acento e sem caixa), ou vazio. O
        da configuração não conta: ele não se troca nem se apaga."""
        atuais = self._atuais()
        preset = atuais.por_nome(nome.strip()) if atuais is not None and nome.strip() else None
        return preset.nome if preset is not None and not preset.da_configuracao else ""

    @Slot(str, str, str, str, str, result=str)
    def salvarPreset(self, nome: str, papel: str, provedor: str, modelo: str, esforco: str) -> str:
        """Acrescenta (ou troca o de mesmo nome) e grava o arquivo do dono. Não ativa e não liga
        nuvem: se o provedor está desligado, a frase diz."""
        nome, modelo = nome.strip(), modelo.strip()
        try:
            # A gravação também recusaria (o arquivo passa pela leitura antes de ir ao disco), mas
            # com a frase de quem achou a chave num arquivo; aqui ela não chegou a arquivo nenhum.
            if any(PARECE_CHAVE.search(v) or OUTRAS_CHAVES.search(v) for v in (nome, modelo)):
                raise PresetsInvalidos(
                    "isso tem a forma de uma chave de API, e chave não entra em preset: guarde-a "
                    "em «chaves de api», nesta tela"
                )
            if normalizar(nome) == normalizar(DA_CONFIGURACAO):
                raise PresetsInvalidos(
                    f"«{DA_CONFIGURACAO}» é o preset que espelha o jarvis-voz.toml: escolha outro "
                    "nome"
                )
            motor = self._motor(provedor)
            if motor is None:
                raise PresetsInvalidos(f"o provedor {provedor[:64]!r} não está no registro")
            if papel not in papeis_de(motor):
                servidos = ", ".join(NOME_DO_PAPEL.get(p, p) for p in papeis_de(motor))
                raise PresetsInvalidos(
                    f"{nome_curto(motor)} não serve para {NOME_DO_PAPEL.get(papel, papel[:20])}: "
                    f"serve para {servidos}"
                )
            if da_decisao(motor) and modelo and modelo not in motor.modelos_permitidos:
                raise PresetsInvalidos(
                    f"{nome_curto(motor)} só roda o que o registro lista "
                    f"({', '.join(motor.modelos_permitidos)}): os limiares do detector foram "
                    "calibrados nele (ADR-0029)"
                )
            atuais = self._para_gravar()
            novos = atuais.com_preset(Preset(nome, papel, provedor, modelo, esforco))
            caminho = self._fonte.gravar(novos)
        except (PresetsInvalidos, OSError) as erro:
            return self._avisar(f"não deu: {erro}")
        salvo = novos.por_nome(nome)
        frase = (
            f"preset «{salvo.nome if salvo else nome}» salvo para "
            f"{NOME_DO_PAPEL[papel]} em {caminho} — escolha-o acima para usar"
        )
        if not esta_ligado(motor, self._provedores()):
            frase += (
                f". {nome_curto(motor)} está desligado: ligue-o aqui, depois do aviso, ou o "
                "pedido é recusado"
            )
        return self._avisar(frase)

    @Slot(str, result=str)
    def apagarPreset(self, nome: str) -> str:
        """Tira o preset do arquivo do dono. Se era o ativo de um papel, o papel fica sem preset
        (o cérebro volta ao da configuração)."""
        try:
            if normalizar(nome) == normalizar(DA_CONFIGURACAO):
                raise PresetsInvalidos(
                    "o da configuração não se apaga: ele é o s2 do jarvis-voz.toml"
                )
            atuais = self._para_gravar()
            preset = atuais.por_nome(nome)
            if preset is None:
                raise PresetsInvalidos(f"não há preset chamado «{nome.strip()[:40]}»")
            era_ativo = self._ativos_de(atuais).get(str(preset.papel)) == preset.nome
            self._fonte.gravar(atuais.sem_preset(preset.nome))
        except (PresetsInvalidos, OSError) as erro:
            return self._avisar(f"não deu: {erro}")
        frase = f"preset «{preset.nome}» apagado"
        if era_ativo:
            frase += (
                " — o cérebro volta ao da configuração"
                if preset.papel == Papel.CEREBRO
                else f" — {NOME_DO_PAPEL.get(str(preset.papel), preset.papel)} fica sem preset"
            )
        return self._avisar(frase)

    @Slot(str, str, result=str)
    def ativar(self, papel: str, nome: str) -> str:
        """O preset ativo do papel, gravado no arquivo do dono. Vazio tira o do papel — no
        cérebro, é voltar ao da configuração. Não liga nuvem: avisa se o provedor está
        desligado."""
        if papel == Papel.CEREBRO and normalizar(nome) == normalizar(DA_CONFIGURACAO):
            nome = ""
        try:
            if papel not in PAPEIS:
                raise PresetsInvalidos(f"o papel {papel[:20]!r} não existe ({', '.join(PAPEIS)})")
            atuais = self._para_gravar()
            novos = atuais.com_ativo(papel, nome)
            pedido = nome or (DA_CONFIGURACAO if papel == Papel.CEREBRO else "")
            # Clicar no que já é o ativo não grava: sem arquivo do dono, gravar criaria um com a
            # cópia do padrão, e o padrão do repositório deixaria de valer para ele.
            if normalizar(self._ativos_de(atuais)[papel]) != normalizar(pedido):
                self._fonte.gravar(novos)
        except (PresetsInvalidos, OSError) as erro:
            return self._avisar(f"não deu: {erro}")
        rotulo = NOME_DO_PAPEL[papel]
        preset = novos.ativo(papel) if nome else None
        if preset is None:
            return self._avisar(
                f"{rotulo}: volta ao da configuração (s2 do jarvis-voz.toml)"
                if papel == Papel.CEREBRO
                else f"{rotulo}: nenhum preset"
            )
        frase = f"{rotulo}: «{preset.nome}» ativo"
        motor = self._motor(preset.provedor)
        if motor is None or not esta_ligado(motor, self._provedores()):
            frase += (
                f" — mas {apelido(motor) if motor else preset.provedor} está desligado: ligue-o "
                "abaixo, depois do aviso, ou o pedido é recusado"
            )
        return self._avisar(frase)

    @Slot(str, bool)
    def ligarProvedor(self, identificador: str, ligado: bool) -> None:
        """O botão depois do aviso (ADR-0017, política 2): liga ou desliga a nuvem deste provedor
        **nesta sessão**; "salvar configuração" é que guarda no arquivo."""
        motor = self._motor(identificador)
        if motor is None:
            self._avisar(f"não deu: o provedor {identificador[:64]!r} não está no registro")
            return
        nome = nome_curto(motor)
        if not motor.na_nuvem:
            self._avisar(f"{nome} roda nesta máquina: não há nuvem para ligar")
            return
        self._ligar_nuvem(motor.id, ligado)
        if ligado:
            self._avisar(f"{nome} ligado nesta sessão — «salvar configuração» guarda no arquivo")
        elif esta_ligado(motor, self._provedores()):
            self._avisar(
                f'{nome} continua ligado pela configuração (s2 = "claude" conta como ligado)'
            )
        else:
            self._avisar(f"{nome} desligado — «salvar configuração» guarda no arquivo")


__all__ = [
    "NOME_DO_PAPEL",
    "PonteDeModelos",
    "apelido",
    "lista_para_a_tela",
    "nome_curto",
    "resumo_das_capacidades",
]
