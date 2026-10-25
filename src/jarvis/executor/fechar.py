"""Fechar a janela × encerrar o app (dono, 2026-10-21; ADR-0042).

"Fecha o Discord" fecha a **janela** dele, como o X: o pedido educado do gerenciador de
janelas (`window.close`) — o app pode perguntar se salva, ou ir para a bandeja, que é o que o X
faria. "Fecha o Discord todo", "mata o Discord", "encerra o Steam inteiro" **encerra o app**
(`apps.quit`): SIGTERM, por PID, às instâncias dele, e SIGKILL — só depois de um prazo curto — ao
que não saiu.

Quem é "o app" é o código que decide, nunca o modelo:

- pelo **nome**: o resolvedor fonético contra os apps instalados (`.desktop`), e entre os
  parecidos o que está aberto; sem nenhum, as janelas cuja classe ou título têm o nome;
- pela **janela** (`janela_id` de um `window.list`) ou pela janela em **primeiro plano** ("fecha
  esse aí", "fecha a janela");
- os processos do app são os do **executável** dele (o do `.desktop`, ou o do processo da janela)
  e os das **janelas** dele, mais os descendentes — nunca um processo achado por nome solto.
  Executável genérico (`python3`, `electron`, `flatpak`…) não conta: aí só valem os PIDs das
  janelas.

O que nunca recebe sinal: o PID 1; processo de outro usuário (ou do root); o próprio Jarvis, quem o
abriu (o terminal em que ele roda) e os processos dele (o `claude -p`, o trabalhador de voz: os da
sessão dele); a casca do desktop (o compositor, o painel, o gerenciador de sessão, o áudio, o
D-Bus). E o sinal só vai a um PID que ainda é o mesmo processo (mesmo início, mesmo dono): PID
reaproveitado não leva sinal. Ambiguidade (dois apps parecidos, várias janelas e nenhuma em primeiro
plano) é pergunta ao dono, nunca palpite.

O "sim" que o alvo pede é dito aqui (`exige_o_sim`) e decidido pelo PDP — só no que é de fato
arriscado (dono, 2026-10-25; ADR-0046): trabalho não salvo **detectado** (a marca no título da
janela), um jogo aberto, app fora da lista que o dono liberou, ou um alvo que o pedido dele não
citou. A ordem explícita do dono ("fecha meu Brave", "fecha o Discord todo") vale sem o sim, também
para o navegador. "O navegador" sem nome é o que está em foco, o único aberto ou o da frente; dois
igualmente plausíveis é pergunta.
"""

from __future__ import annotations

import os
import re
import signal
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from jarvis.apps.resolvedor import ResolvedorDeApps
from jarvis.executor.comandos import ComandoIndisponivel
from jarvis.executor.janelas import (
    GENERICOS,
    FechaJanelas,
    JanelaDoSistema,
    Janelas,
    PistaDoApp,
    de_app,
)
from jarvis.executor.lancador import App

PRAZO_DO_TERM_S: Final = 3.0
"""Depois do SIGTERM, quanto o app tem para sair sozinho antes do SIGKILL."""
INTERVALO_S: Final = 0.1
ESPERA_DA_JANELA_S: Final = 1.5
"""Quanto se espera a janela sumir da lista, para dizer que fechou (ou que o app perguntou algo)."""
LIMITE_DE_PROCESSOS: Final = 400
"""Um app com mais processos do que isso não é encerrado por voz: o alvo está errado."""
PROTEGIDOS: Final = frozenset(
    {
        "init", "kwin", "kwin_wayland", "kwin_x11", "kwin_wayland_wrapper", "plasmashell",
        "krunner", "ksmserver", "kded5", "kded6", "kglobalacceld", "kactivitymanagerd",
        "ksplashqml", "startplasma-wayland", "startplasma-x11", "plasma_session",
        "plasma-session", "org_kde_powerdevil", "kwalletd5", "kwalletd6", "xembedsniproxy",
        "gmenudbusmenuproxy", "kaccess", "polkit-kde-authentication-agent-1", "polkitd",
        "xdg-desktop-portal", "xdg-desktop-portal-kde", "xdg-desktop-portal-gtk",
        "xdg-desktop-portal-gnome", "xdg-document-portal", "xdg-permission-store",
        "xwayland", "xorg", "x", "gnome-shell", "gnome-session", "gnome-session-binary", "mutter",
        "gdm", "gdm-wayland-session", "gdm-x-session", "sddm", "sddm-helper", "lightdm",
        "pipewire", "pipewire-pulse", "wireplumber", "pulseaudio", "dbus-daemon", "dbus-broker",
        "dbus-broker-launch", "at-spi-bus-launcher", "at-spi2-registryd", "login", "agetty",
        "sshd", "ssh-agent", "gpg-agent", "gvfsd", "ibus-daemon", "fcitx5", "baloo_file",
    }
)  # fmt: skip
"""A sessão do desktop: matar um destes derruba a tela, o som ou o login do dono. Nunca é alvo."""
MARCAS_DE_NAO_SALVO: Final = (
    r"^\s*[*●•]",
    r"\s[*●]\s",
    r"[*●]\s*$",
    r"[(\[]\s*(?:modificad[oa]|modified|não salvo|nao salvo|unsaved)\s*[)\]]",
    r"\b(?:não salvo|nao salvo|unsaved changes|alterações não salvas)\b",
)
"""Como o título diz que há trabalho não salvo: o `*` ou o `●` do Kate, do VS Code, do GIMP, do
Inkscape, do Blender; o "[modificado]" e o "não salvo" de outros (dono, 2026-10-25: o sim só para o
trabalho não salvo **detectado**, não para todo editor aberto)."""
EXECUTAVEIS_SEM_MARCA: Final = frozenset({"soffice", "soffice.bin", "libreoffice"})
"""Apps cujo título não marca o documento alterado (o LibreOffice): com um documento aberto, o
código não sabe se está salvo — e um SIGTERM nele perde o que não foi salvo. Conta como
detectado."""
TITULOS_SEM_DOCUMENTO: Final = frozenset({"libreoffice", "centro inicial do libreoffice"})
CATEGORIAS_DO_SISTEMA: Final = frozenset({"System", "Settings"})
GENERICOS_DO_NAVEGADOR: Final = frozenset(
    {"navegador", "browser", "navegador de internet", "navegador web", "internet"}
)
"""Como o dono chama o navegador sem dizer qual («fecha o navegador»)."""
_POSSE: Final = (
    r"^(?:(?:o|a|os|as)\s+)?"
    r"(?:meu|minha|meus|minhas|seu|sua|nosso|nossa|esse|essa|este|esta|aquele|aquela|o|a|os|as)\s+"
)
DEITICOS: Final = frozenset(
    {"janela", "esse", "essa", "isso", "este", "esta", "isto", "aqui", "atual", "frente"}
)
"""As palavras de quem fecha "o que está aí" sem dizer o nome: «fecha a janela», «fecha esse aí»."""
NAVEGADORES_CONHECIDOS: Final = frozenset(
    {
        "firefox", "firefox-bin", "brave", "brave-browser", "chrome", "google-chrome", "chromium",
        "chromium-browser", "vivaldi", "vivaldi-bin", "opera", "msedge", "microsoft-edge",
        "librewolf", "zen", "zen-browser", "floorp", "falkon", "epiphany",
    }
)  # fmt: skip
CLASSES_DO_JARVIS: Final = frozenset({"jarvis", "dev.sodredev.jarvis"})


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.casefold().split())


def sem_posse(pedido: str) -> str:
    """«meu Brave» → «Brave», «o meu navegador» → «navegador»: o nome, sem artigo nem posse."""
    return re.sub(_POSSE, "", pedido.strip(), flags=re.IGNORECASE).strip()


def nao_salvo(titulo: str) -> bool:
    """O título da janela diz que há trabalho não salvo (o `*`, o `●`, o "[modificado]")."""
    return any(re.search(marca, titulo, flags=re.IGNORECASE) for marca in MARCAS_DE_NAO_SALVO)


def _palavras(texto: str) -> str:
    return " " + " ".join(re.findall(r"\w+", _dobrar(texto))) + " "


# --- os processos ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Processo:
    """O que se lê de um processo para saber se ele é do app e se pode receber sinal. Nunca o
    ambiente dele (pode ter chave de API) nem a memória: o `stat`, o dono e o executável."""

    pid: int
    pai: int
    uid: int
    executavel: str
    inicio: int
    """`starttime` do `/proc/<pid>/stat`: o mesmo PID com outro início é outro processo."""
    sessao: int
    estado: str = "S"
    """`Z` = zumbi: já saiu, só falta o pai recolher."""


class TabelaDeProcessos(Protocol):
    def listar(self) -> list[Processo]: ...

    def ler(self, pid: int) -> Processo | None: ...

    def argumentos(self, pid: int) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class TabelaDoProc:
    """Linux: o `/proc`. Só o `stat`, o `status` (o dono), o `exe` e — para o jogo do Steam — a
    linha de comando."""

    raiz: Path = Path("/proc")

    def listar(self) -> list[Processo]:
        processos = []
        try:
            entradas = list(self.raiz.iterdir())
        except OSError:
            return []
        for entrada in entradas:
            if entrada.name.isdigit():
                processo = self.ler(int(entrada.name))
                if processo is not None:
                    processos.append(processo)
        return processos

    def ler(self, pid: int) -> Processo | None:
        pasta = self.raiz / str(pid)
        try:
            bruto = (pasta / "stat").read_text("utf-8", errors="replace")
            status = (pasta / "status").read_text("utf-8", errors="replace")
        except OSError:
            return None
        fecha = bruto.rfind(")")
        if fecha < 0:
            return None
        comm = bruto[bruto.find("(") + 1 : fecha]
        campos = bruto[fecha + 2 :].split()
        uids = next(
            (linha.split()[1:] for linha in status.splitlines() if linha.startswith("Uid:")), []
        )
        # Real, efetivo, salvo e de arquivo têm de ser o mesmo: um setuid é de outro dono.
        uid = int(uids[0]) if uids and len(set(uids)) == 1 and uids[0].isdigit() else -1
        try:
            executavel = (pasta / "exe").readlink().name
        except OSError:
            executavel = comm
        try:
            return Processo(
                pid=pid,
                pai=int(campos[1]),
                uid=uid,
                executavel=executavel.removesuffix(" (deleted)"),
                inicio=int(campos[19]),
                sessao=int(campos[3]),
                estado=campos[0],
            )
        except (IndexError, ValueError):
            return None

    def argumentos(self, pid: int) -> tuple[str, ...]:
        try:
            with (self.raiz / str(pid) / "cmdline").open("rb") as arquivo:
                bruto = arquivo.read(8192)
        except OSError:
            return ()
        return tuple(a.decode("utf-8", "replace") for a in bruto.split(b"\0") if a)


Sinalizar = Callable[[int, int], None]


# --- quem é o Jarvis ------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Jarvis:
    """O próprio Jarvis, que nunca é alvo: ele, quem o abriu e os processos dele."""

    pid: int
    uid: int
    sessao: int
    ancestrais: frozenset[int] = frozenset()

    @classmethod
    def deste_processo(cls, tabela: TabelaDeProcessos) -> Jarvis:
        pid = os.getpid()
        ancestrais: set[int] = set()
        atual = os.getppid()
        for _ in range(64):
            if atual <= 1 or atual in ancestrais:
                break
            ancestrais.add(atual)
            processo = tabela.ler(atual)
            if processo is None:
                break
            atual = processo.pai
        return cls(pid=pid, uid=os.getuid(), sessao=os.getsid(0), ancestrais=frozenset(ancestrais))


def _filhos(processos: Iterable[Processo]) -> dict[int, list[Processo]]:
    filhos: dict[int, list[Processo]] = {}
    for processo in processos:
        filhos.setdefault(processo.pai, []).append(processo)
    return filhos


def _descendentes(raiz: int, filhos: Mapping[int, list[Processo]]) -> list[Processo]:
    achados: list[Processo] = []
    pilha = list(filhos.get(raiz, ()))
    vistos: set[int] = set()
    while pilha and len(achados) < LIMITE_DE_PROCESSOS:
        processo = pilha.pop()
        if processo.pid in vistos:
            continue
        vistos.add(processo.pid)
        achados.append(processo)
        pilha.extend(filhos.get(processo.pid, ()))
    return achados


def protecao(processo: Processo, jarvis: Jarvis, internos: frozenset[int]) -> str:
    """Por que este processo nunca recebe sinal (vazio = pode). `internos` são os processos do
    próprio Jarvis (descendentes dele na mesma sessão)."""
    nome = _dobrar(processo.executavel)
    if processo.pid <= 1:
        return "é o processo inicial do sistema"
    if processo.uid != jarvis.uid:
        return "é de outro usuário ou do sistema"
    if processo.pid == jarvis.pid or processo.pid in internos:
        return "é o próprio Jarvis — para isso, peça para encerrar o Jarvis"
    if processo.pid in jarvis.ancestrais:
        return "o Jarvis está rodando dentro dele"
    if nome in PROTEGIDOS or nome.startswith("systemd"):
        return "é parte da sessão do desktop"
    return ""


# --- o alvo ---------------------------------------------------------------------------------------
class AlvoRecusado(ValueError):
    """Não há alvo certo: não está aberto, é ambíguo, ou é protegido. A frase vai ao modelo."""

    def __init__(self, motivo: str, causa: str) -> None:
        super().__init__(motivo)
        self.causa = causa


@dataclass(frozen=True, slots=True)
class Identidade:
    """Como reconhecer o app: os executáveis e as classes de janela que só ele teria."""

    nome: str
    executaveis: frozenset[str]
    classes: frozenset[str]
    app: App | None = None


@dataclass(frozen=True, slots=True)
class JanelaAlvo:
    janela: JanelaDoSistema
    nome: str
    exige_o_sim: str = ""


@dataclass(frozen=True, slots=True)
class AppAlvo:
    nome: str
    raizes: tuple[Processo, ...]
    """As instâncias: o SIGTERM vai a elas (os filhos saem com o pai)."""
    processos: tuple[Processo, ...]
    """Tudo o que é do app (as instâncias e os descendentes): o que sobrar depois do prazo leva
    SIGKILL."""
    janelas: tuple[JanelaDoSistema, ...] = ()
    exige_o_sim: str = ""


@dataclass(slots=True)
class Fechador:
    """As portas para resolver e agir — todas injetáveis: nenhum teste toca o desktop do dono."""

    janelas: Janelas | None
    tabela: TabelaDeProcessos = field(default_factory=TabelaDoProc)
    catalogo: Mapping[str, App] = field(default_factory=dict)
    navegadores: frozenset[str] = frozenset()
    """As famílias de navegador que o dono configurou (`brave`, `firefox`…)."""
    sinalizar: Sinalizar = os.kill
    dormir: Callable[[float], None] = time.sleep
    relogio: Callable[[], float] = time.monotonic
    jarvis: Jarvis | None = None
    prazo_do_term_s: float = PRAZO_DO_TERM_S
    liberados: frozenset[str] | None = None
    """Os apps que o dono liberou (ids e nomes, sem acento nem caixa). Encerrar um app fora daqui
    pede o sim (ADR-0046); `None` = a lista não é conhecida aqui, e a regra não se aplica."""

    def _o_jarvis(self) -> Jarvis:
        if self.jarvis is None:
            self.jarvis = Jarvis.deste_processo(self.tabela)
        return self.jarvis

    def _janelas(self) -> list[JanelaDoSistema]:
        if self.janelas is None:
            raise AlvoRecusado(
                "nesta sessão não há como ver as janelas (no Wayland do KDE, instale o kdotool)",
                "sem_janelas",
            )
        return [j for j in self.janelas.listar() if de_app(j)]

    # --- quem é o app ---------------------------------------------------------------------------
    def _identidade(
        self, pedido: str, janela: JanelaDoSistema | None, lista: list[JanelaDoSistema]
    ) -> Identidade:
        if janela is not None:
            return self._identidade_da_janela(janela)
        pedido = sem_posse(pedido)  # «meu Brave» é o Brave
        if _dobrar(pedido) in GENERICOS_DO_NAVEGADOR:
            return self._o_navegador(lista)
        app = self._do_catalogo(pedido, lista)
        if app is not None:
            return _identidade_do_app(app)
        alvo = _dobrar(pedido)
        achadas = [
            j for j in lista if alvo and (alvo in _dobrar(j.classe) or alvo in _dobrar(j.titulo))
        ]
        exatas = [j for j in achadas if _dobrar(j.classe) == alvo]
        achadas = exatas or achadas
        if not achadas:
            if alvo in PROTEGIDOS or alvo.startswith("systemd"):
                raise AlvoRecusado(
                    f"não encerro o {pedido}: é parte da sessão do desktop", "alvo_protegido"
                )
            raise AlvoRecusado(f"não achei nada aberto chamado «{pedido}»", "alvo_ausente")
        classes = {_dobrar(j.classe) for j in achadas}
        if len(classes) > 1:
            raise AlvoRecusado(
                "mais de um app casa com «"
                + pedido
                + "»: "
                + ", ".join(sorted({j.classe for j in achadas}))
                + ". Qual deles?",
                "alvo_ambiguo",
            )
        return self._identidade_da_janela(achadas[0])

    def _o_navegador(self, lista: list[JanelaDoSistema]) -> Identidade:
        """«O navegador», sem nome (dono, 2026-10-25): o que está em foco; senão o único aberto;
        senão o único na frente de um monitor; senão o único visível. Dois igualmente plausíveis é
        pergunta, nunca palpite."""
        abertos = [
            (j, ident) for j in lista if self._navegador(ident := self._identidade_da_janela(j))
        ]
        if not abertos:
            raise AlvoRecusado("nenhum navegador está aberto", "alvo_ausente")
        criterios: tuple[Callable[[JanelaDoSistema], bool], ...] = (
            lambda j: j.ativa,
            lambda _j: True,
            lambda j: j.na_frente and not j.minimizada,
            lambda j: j.visivel and not j.minimizada,
        )
        for criterio in criterios:
            achados = {_dobrar(i.nome): i for j, i in abertos if criterio(j)}
            if len(achados) == 1:
                return next(iter(achados.values()))
        nomes = sorted({i.nome for _j, i in abertos})
        raise AlvoRecusado(
            f"há mais de um navegador aberto ({' e '.join(nomes)}). Qual deles?", "alvo_ambiguo"
        )

    def _citado(self, identidade: Identidade, fala: str, *, sem_nome: bool) -> bool:
        """O pedido do dono cita este alvo: pelo nome (o do app, um apelido, o executável, a classe
        da janela), por «navegador» quando é um navegador, ou por «essa janela», «esse aí» quando é
        a da frente. Sem isso, a ordem não foi explícita — veio do modelo, ou de um texto lido."""
        dita = _palavras(fala)
        app = identidade.app
        nomes = {identidade.nome, *identidade.executaveis, *identidade.classes}
        if app is not None:
            nomes |= {app.nome, *app.nomes, app.id}
        candidatos: set[str] = set()
        for nome in nomes:
            partes = re.findall(r"\w+", _dobrar(nome.rsplit(".", 1)[-1]))
            if partes:
                candidatos.add(" ".join(partes))
                if len(partes[0]) >= 3:
                    candidatos.add(partes[0])  # «brave» de «Brave Web Browser»
        if any(f" {c} " in dita for c in candidatos):
            return True
        if self._navegador(identidade) and (" navegador " in dita or " browser " in dita):
            return True
        return sem_nome and any(f" {d} " in dita for d in DEITICOS)

    def _liberado(self, identidade: Identidade) -> bool:
        if self.liberados is None or self._navegador(identidade):
            return True  # sem a lista, a regra não vale; o navegador configurado é do dono
        app = identidade.app
        nomes = {_dobrar(identidade.nome)}
        if app is not None:
            nomes |= {_dobrar(app.id), *(_dobrar(n) for n in app.nomes)}
        return bool(nomes & self.liberados)

    def _identidade_da_janela(self, janela: JanelaDoSistema) -> Identidade:
        executaveis: set[str] = set()
        if janela.pid is not None:
            processo = self.tabela.ler(janela.pid)
            if processo is not None and _dobrar(processo.executavel) not in GENERICOS:
                executaveis.add(_dobrar(processo.executavel))
        app = next(
            (
                a
                for a in self._apps()
                if _dobrar(janela.classe) in _identidade_do_app(a).classes
                or (executaveis & _identidade_do_app(a).executaveis)
            ),
            None,
        )
        if app is not None:
            identidade = _identidade_do_app(app)
            return Identidade(
                app.nome,
                identidade.executaveis | executaveis,
                identidade.classes | {_dobrar(janela.classe)},
                app,
            )
        return Identidade(
            janela.classe or janela.titulo[:40],
            frozenset(executaveis),
            frozenset({_dobrar(janela.classe)} if janela.classe else set()),
        )

    def _apps(self) -> list[App]:
        """Os apps de verdade do catálogo (`.desktop` que aparece no menu), sem os binários soltos
        do PATH: "fecha o code" não pode casar com um utilitário qualquer."""
        return [
            a
            for a in self.catalogo.values()
            if a.arquivo.suffix == ".desktop" and not a.sem_exibicao
        ]

    def _do_catalogo(self, pedido: str, lista: list[JanelaDoSistema]) -> App | None:
        apps = self._apps()
        if not pedido.strip() or not apps:
            return None
        resolucao = ResolvedorDeApps(apps).resolver(pedido)
        if resolucao.estado == "encontrado" and isinstance(resolucao.app, App):
            return resolucao.app
        if resolucao.estado != "ambiguo":
            return None
        # Entre os parecidos, o que está aberto: "fecha o code" só com o VS Code aberto não é
        # dúvida.
        abertos = [
            c.app
            for c in resolucao.candidatos
            if isinstance(c.app, App) and self._aberto(_identidade_do_app(c.app), lista)
        ]
        if len(abertos) == 1:
            return abertos[0]
        raise AlvoRecusado(
            f"não sei qual: {resolucao.pergunta} Diga o nome completo.", "alvo_ambiguo"
        )

    def _aberto(self, identidade: Identidade, lista: list[JanelaDoSistema]) -> bool:
        if any(_dobrar(j.classe) in identidade.classes for j in lista):
            return True
        return any(
            _dobrar(p.executavel) in identidade.executaveis
            for p in self.tabela.listar()
            if p.uid == self._o_jarvis().uid
        )

    # --- a janela -------------------------------------------------------------------------------
    def janela(
        self, pedido: str = "", janela_id: str = "", *, fala: str | None = None
    ) -> JanelaAlvo:
        """A janela que `window.close` fecha: a do id, a do app pelo nome ou a em primeiro plano.
        `fala` é o pedido do dono: com ela, o código sabe se a ordem foi explícita (ADR-0046);
        `None` = não se sabe, e vale como explícita."""
        lista = self._janelas()
        if janela_id:
            janela = next((j for j in lista if j.id == janela_id), None)
            if janela is None:
                raise AlvoRecusado("essa janela não está mais aberta", "alvo_ausente")
        elif pedido.strip():
            identidade = self._identidade(pedido, None, lista)
            do_app = self._janelas_de(identidade, lista)
            if not do_app:
                raise AlvoRecusado(f"o {identidade.nome} não tem janela aberta", "alvo_ausente")
            ativas = [j for j in do_app if j.ativa]
            # Várias janelas e nenhuma em foco: a da frente de um monitor, se for uma só.
            na_frente = [j for j in do_app if j.na_frente and not j.minimizada]
            escolhidas = ativas or (na_frente if len(na_frente) == 1 else [])
            if len(do_app) > 1 and not escolhidas:
                titulos = "; ".join(f"«{j.titulo[:40]}»" for j in do_app[:4])
                raise AlvoRecusado(
                    f"o {identidade.nome} tem {len(do_app)} janelas abertas ({titulos}). Qual?",
                    "alvo_ambiguo",
                )
            janela = escolhidas[0] if escolhidas else do_app[0]
        else:
            janela = next((j for j in lista if j.ativa), None)
            if janela is None:
                raise AlvoRecusado("não sei qual janela está em primeiro plano", "alvo_ausente")
        jarvis = self._o_jarvis()
        if _dobrar(janela.classe) in CLASSES_DO_JARVIS or janela.pid == jarvis.pid:
            raise AlvoRecusado(
                "essa é a janela do próprio Jarvis: para fechá-lo, peça para encerrar o Jarvis",
                "alvo_protegido",
            )
        identidade = self._identidade_da_janela(janela)
        explicito = fala is None or self._citado(
            identidade, fala, sem_nome=not (pedido.strip() or janela_id)
        )
        motivo = "" if explicito else self._sim_da_janela(identidade)
        return JanelaAlvo(janela, identidade.nome, motivo)

    def _janelas_de(
        self, identidade: Identidade, lista: list[JanelaDoSistema]
    ) -> list[JanelaDoSistema]:
        def do_app(janela: JanelaDoSistema) -> bool:
            if _dobrar(janela.classe) in identidade.classes:
                return True
            if janela.pid is None or not identidade.executaveis:
                return False
            processo = self.tabela.ler(janela.pid)
            return processo is not None and _dobrar(processo.executavel) in identidade.executaveis

        return [j for j in lista if do_app(j)]

    def _sim_da_janela(self, identidade: Identidade) -> str:
        """Fechar a janela é o X: o app pergunta se salva. Só a janela que o dono **não citou** —
        o modelo decidiu, ou um texto lido sugeriu — pede o sim, e só a do navegador (as abas vão
        junto) ou a de um programa do sistema."""
        if self._navegador(identidade):
            return (
                f"o {identidade.nome}, o seu navegador, ficou de fora do que você pediu, e a "
                "janela fecha com as abas dela"
            )
        if identidade.app is not None and set(identidade.app.categorias) & CATEGORIAS_DO_SISTEMA:
            return f"o {identidade.nome}, um programa do sistema, ficou de fora do que você pediu"
        return ""

    def fechar_janela(self, alvo: JanelaAlvo) -> dict[str, Any]:
        """O pedido educado do gerenciador de janelas; e confere se a janela sumiu."""
        porta: object = self.janelas  # a porta que lista pode não fechar (as de teste antigas)
        if not isinstance(porta, FechaJanelas) or not porta.fechar(alvo.janela.id):
            raise ComandoIndisponivel("o gerenciador de janelas não aceitou fechar a janela")
        dados: dict[str, Any] = {
            "app": alvo.nome,
            "titulo": alvo.janela.titulo[:100],
            "janela_id": alvo.janela.id,
        }
        fim = self.relogio() + ESPERA_DA_JANELA_S
        assert self.janelas is not None
        while self.relogio() < fim:
            self.dormir(INTERVALO_S)
            if all(j.id != alvo.janela.id for j in self.janelas.listar()):
                return {**dados, "fechada": True}
        return {
            **dados,
            "fechada": False,
            "nota": "a janela continua aberta: o app pode estar perguntando se salva",
        }

    # --- o app ----------------------------------------------------------------------------------
    def app(self, pedido: str = "", janela_id: str = "", *, fala: str | None = None) -> AppAlvo:
        """O app que `apps.quit` encerra: os processos dele, conferidos e protegidos. `fala` é o
        pedido do dono (a ordem foi explícita?); `None` = não se sabe, e vale como explícita."""
        lista = self._janelas() if self.janelas is not None else []
        if janela_id or not pedido.strip():
            if self.janelas is None:
                self._janelas()  # sem porta, não há janela em primeiro plano: recusa dizendo
            janela = (
                next((j for j in lista if j.id == janela_id), None)
                if janela_id
                else next((j for j in lista if j.ativa), None)
            )
            if janela is None:
                motivo = (
                    "essa janela não está mais aberta"
                    if janela_id
                    else ("não sei qual janela está em primeiro plano")
                )
                raise AlvoRecusado(motivo, "alvo_ausente")
            identidade = self._identidade(pedido, janela, lista)
            janelas_do_pid = [janela]
        else:
            identidade = self._identidade(pedido, None, lista)
            janelas_do_pid = self._janelas_de(identidade, lista)
        jarvis = self._o_jarvis()
        todos = [p for p in self.tabela.listar() if p.estado != "Z"]
        por_pid = {p.pid: p for p in todos}
        filhos = _filhos(todos)
        internos = frozenset(
            p.pid for p in _descendentes(jarvis.pid, filhos) if p.sessao == jarvis.sessao
        )
        escolhidos: dict[int, Processo] = {}
        for processo in todos:
            if (
                processo.uid == jarvis.uid
                and _dobrar(processo.executavel) in identidade.executaveis
            ):
                escolhidos[processo.pid] = processo
        for janela in janelas_do_pid:
            if janela.pid is not None and janela.pid in por_pid:
                escolhidos[janela.pid] = por_pid[janela.pid]
        if not escolhidos:
            raise AlvoRecusado(f"o {identidade.nome} não está aberto", "alvo_ausente")
        raizes = [p for p in escolhidos.values() if p.pai not in escolhidos]
        for raiz in raizes:
            porque = protecao(raiz, jarvis, internos)
            if porque:
                raise AlvoRecusado(f"não encerro o {identidade.nome}: {porque}", "alvo_protegido")
        processos: dict[int, Processo] = {}
        for raiz in raizes:
            for processo in (raiz, *_descendentes(raiz.pid, filhos)):
                if not protecao(processo, jarvis, internos):
                    processos[processo.pid] = processo
        if len(processos) > LIMITE_DE_PROCESSOS:
            raise AlvoRecusado(
                f"o {identidade.nome} casou com {len(processos)} processos: não encerro por voz",
                "alvo_ambiguo",
            )
        explicito = fala is None or self._citado(
            identidade, fala, sem_nome=not (pedido.strip() or janela_id)
        )
        do_app = self._janelas_de(identidade, lista) if lista else list(janelas_do_pid)
        motivo = self._sim_do_app(
            identidade, tuple(processos.values()), do_app, explicito=explicito
        )
        return AppAlvo(
            nome=identidade.nome,
            raizes=tuple(raizes),
            processos=tuple(processos.values()),
            janelas=tuple(janelas_do_pid),
            exige_o_sim=motivo,
        )

    def _navegador(self, identidade: Identidade) -> bool:
        nomes = {*identidade.executaveis, *identidade.classes, _dobrar(identidade.nome)}
        if nomes & NAVEGADORES_CONHECIDOS or any(
            f in n for f in self.navegadores for n in nomes if f
        ):
            return True
        app = identidade.app
        return app is not None and "https" in app.esquemas

    def _sim_do_app(
        self,
        identidade: Identidade,
        processos: tuple[Processo, ...],
        janelas: list[JanelaDoSistema],
        *,
        explicito: bool,
    ) -> str:
        """O sim só no que é de fato arriscado (dono, 2026-10-25; ADR-0046): um jogo aberto (o
        progresso), trabalho não salvo **detectado** (a marca no título), app fora da lista que o
        dono liberou, ou um alvo que o pedido dele não citou. A ordem explícita de encerrar o
        navegador, um app de várias instâncias ou um do sistema vale sem perguntar. As frases não
        trazem "sim", "pode" nem "não": a pergunta falada não pode soar como resposta no eco."""
        motivos: list[str] = []
        nome = identidade.nome
        jogo = any(
            "SteamLaunch" in self.tabela.argumentos(p.pid) or p.executavel == "reaper"
            for p in processos
        ) or any(c.startswith("steam_app_") for c in identidade.classes)
        if jogo:
            motivos.append("o jogo aberto perde o progresso ainda por salvar")
        sujas = [j for j in janelas if nao_salvo(j.titulo)]
        if sujas:
            motivos.append(f"há trabalho por salvar no {nome} («{sujas[0].titulo[:40]}»)")
        elif identidade.executaveis & EXECUTAVEIS_SEM_MARCA and any(
            _dobrar(j.titulo) not in TITULOS_SEM_DOCUMENTO for j in janelas
        ):
            motivos.append(f"o {nome} está com documento aberto, e ele não mostra se está salvo")
        if not self._liberado(identidade):
            motivos.append(f"o {nome} está fora da sua lista de apps liberados")
        if not explicito:
            motivos.append(f"o {nome} ficou de fora do que você pediu")
        return "; e ".join(motivos)

    def encerrar_app(self, alvo: AppAlvo) -> dict[str, Any]:
        """SIGTERM às instâncias, o prazo, SIGKILL ao que sobrou; e confere. Cada sinal vai só a um
        PID que ainda é o mesmo processo (mesmo início, mesmo dono) e não é protegido."""
        jarvis = self._o_jarvis()

        def vivo(processo: Processo) -> bool:
            agora = self.tabela.ler(processo.pid)
            return (
                agora is not None
                and agora.inicio == processo.inicio
                and agora.uid == processo.uid
                and agora.estado != "Z"
            )

        def pode(processo: Processo) -> bool:
            return vivo(processo) and not protecao(processo, jarvis, frozenset())

        terminados = 0
        for raiz in alvo.raizes:
            if pode(raiz):
                self._sinal(raiz.pid, signal.SIGTERM)
                terminados += 1
        fim = self.relogio() + self.prazo_do_term_s
        while self.relogio() < fim and any(vivo(p) for p in alvo.processos):
            self.dormir(INTERVALO_S)
        forcados = 0
        for processo in alvo.processos:
            if pode(processo):
                self._sinal(processo.pid, signal.SIGKILL)
                forcados += 1
        if forcados:
            self.dormir(INTERVALO_S)
        sobraram = [p for p in alvo.processos if vivo(p)]
        return {
            "app": alvo.nome,
            "instancias": len(alvo.raizes),
            "processos": len(alvo.processos),
            "sigterm": terminados,
            "sigkill": forcados,
            "conferido": not sobraram,
        }

    def _sinal(self, pid: int, sinal: int) -> None:
        try:
            self.sinalizar(pid, sinal)
        except ProcessLookupError:  # saiu entre a conferência e o sinal: nada a fazer
            return


def _identidade_do_app(app: App) -> Identidade:
    """As classes que só este app teria (as da ADR-0037: `StartupWMClass`, o id do `.desktop`, o
    executável) e o executável dele, se não for genérico."""
    executavel = _dobrar(app.exec_nome or (Path(app.argv[0]).name if app.argv else ""))
    pista = PistaDoApp.do_app(
        app.nome, app.nomes, app.argv, None, arquivo=app.arquivo, id_do_desktop=app.id
    )
    return Identidade(
        nome=app.nome,
        executaveis=frozenset({executavel} - GENERICOS - {""}),
        classes=pista.classes,
        app=app,
    )


__all__ = [
    "AlvoRecusado",
    "AppAlvo",
    "Fechador",
    "JanelaAlvo",
    "Jarvis",
    "Processo",
    "TabelaDeProcessos",
    "TabelaDoProc",
    "protecao",
]
