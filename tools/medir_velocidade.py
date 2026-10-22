"""Velocidade do pedido, por etapa: antes (a trilha do dono) e depois (o código novo, medido aqui).

    uv run --frozen python tools/medir_velocidade.py [--trilha CAMINHO] [--desde 2026-10-21]
        [--rede] [--n 50] [--saida docs/medicoes/velocidade-pedido.md]

Pedido do dono (2026-10-21): «precisa ser muito rápido» — medir o caminho de um pedido típico
(ouvir → ASR → portão → cérebro → 1ª ferramenta → resposta/TTS), com p50/p95 por etapa, antes e
depois. As fontes, cada uma dita na tabela:

1. **Antes — a trilha de diagnóstico do dono** (`~/.local/state/jarvis/voz/diagnostico/`, só
   metadados: tempos, códigos, nomes de ferramenta; nunca fala, URL ou argumento). São os turnos
   de verdade dele, com o `claude -p`, a extensão, a Groq e a ElevenLabs.
2. **Depois — o caminho rápido com o código de verdade** (cérebro, executor, PDP e auditoria em
   SQLite numa pasta temporária), sem LLM: o tempo que é **nosso** até a primeira ferramenta e
   até a primeira frase. As ferramentas aqui são de mentira (respondem na hora): o tempo delas no
   desktop do dono vem da trilha dele (o `apps.launch`, a extensão) e do KWin virtual
   (`docs/medicoes/foco-kwin-virtual.md`).
3. **Rede** (`--rede`, opcional): conexão nova × reaproveitada com a Groq e a ElevenLabs, por
   `ConexoesPersistentes`, num GET **sem autenticação** (nenhuma chave lida, nada cobrado).
4. **Máquina**: CPU, fios, RAM, a GPU que o `nvidia-smi` vê, e as threads do embedding da memória.

Nada aqui toca o microfone, o áudio, o navegador ou as janelas do dono.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from jarvis.medicao import hardware, percentil  # noqa: E402

TRILHA_PADRAO: Final = Path.home() / ".local" / "state" / "jarvis" / "voz" / "diagnostico"
DE_NAVEGACAO: Final = frozenset({"browser.navigate", "sites.open"})


# --- 1. antes: a trilha do dono ----------------------------------------------------------------
def _eventos(pasta: Path) -> list[dict[str, Any]]:
    eventos: list[dict[str, Any]] = []
    for arquivo in sorted(pasta.glob("turnos.jsonl*"), reverse=True):
        try:
            linhas = arquivo.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for linha in linhas:
            try:
                evento = json.loads(linha)
            except ValueError:
                continue
            if isinstance(evento, dict) and "turno" in evento and "t" in evento:
                eventos.append(evento)
    return sorted(eventos, key=lambda e: float(e["t"]))


@dataclass
class Etapas:
    valores: dict[str, list[float]] = field(default_factory=dict)
    contagens: dict[str, int] = field(default_factory=dict)

    def pôr(self, etapa: str, valor: object) -> None:
        if isinstance(valor, int | float) and not isinstance(valor, bool) and valor >= 0:
            self.valores.setdefault(etapa, []).append(float(valor))

    def contar(self, nome: str, quantos: int = 1) -> None:
        self.contagens[nome] = self.contagens.get(nome, 0) + quantos


def etapas_da_trilha(eventos: Iterable[Mapping[str, Any]], desde: float = 0.0) -> Etapas:
    """As etapas dos turnos com método ou ferramenta (os de conversa curta, como «Jarvis.» sozinho,
    não dizem nada sobre o caminho de um pedido)."""
    turnos: dict[str, list[Mapping[str, Any]]] = {}
    for evento in eventos:
        if float(evento["t"]) >= desde:
            turnos.setdefault(str(evento["turno"]), []).append(evento)
    etapas = Etapas()
    for lista in turnos.values():
        inicio = next((e for e in lista if e.get("evento") == "turno.inicio"), None)
        fim = next((e for e in lista if e.get("evento") == "turno.fim"), None)
        metodo = next((e for e in lista if e.get("evento") == "metodo"), {})
        ferramentas = [e for e in lista if e.get("evento") in ("ferramenta", "ferramenta.inicio")]
        if inicio is None or fim is None:
            continue
        if metodo.get("metodo", "conversa") == "conversa" and not ferramentas:
            continue
        t0 = float(inicio["t"])
        etapas.contar("turnos")
        etapas.pôr("fala do dono (ms)", fim.get("ms_ouvido"))
        etapas.pôr("ASR (ms)", fim.get("ms_asr"))
        etapas.pôr("contexto do cérebro (ms)", fim.get("ms_contexto"))
        if fim.get("motor_chamado") is not False:
            etapas.pôr("1º token do motor (ms)", fim.get("ms_primeiro_token"))
        if ferramentas:
            etapas.pôr(
                "1ª ferramenta (ms desde o turno)",
                (float(ferramentas[0]["t"]) - t0) * 1000.0,
            )
        etapas.pôr("1ª fala (ms)", fim.get("ms_primeira_fala"))
        etapas.pôr("1º áudio (ms)", fim.get("ms_primeiro_audio"))
        fala, audio = fim.get("ms_primeira_fala"), fim.get("ms_primeiro_audio")
        if isinstance(fala, int | float) and isinstance(audio, int | float) and audio >= fala:
            etapas.pôr("TTS: da 1ª fala ao 1º áudio (ms)", audio - fala)
        navegou = [
            e
            for e in lista
            if e.get("evento") == "ferramenta"
            and e.get("tool_id") in DE_NAVEGACAO
            and e.get("status") == "ok"
        ]
        if navegou:
            etapas.pôr(
                "pedido de site: até a 1ª página aberta (ms)",
                (float(navegou[0]["t"]) - t0) * 1000.0,
            )
        for e in lista:
            if e.get("evento") != "ferramenta":
                continue
            etapas.pôr(f"ferramenta {e.get('tool_id')} (ms)", e.get("ms"))
            if e.get("tool_id") == "web.buscar":
                etapas.contar("web.buscar (a aba escondida, sem chave)")
            if e.get("tool_id") in DE_NAVEGACAO and e.get("status") == "erro":
                etapas.contar("navegação com erro (o id velho: «falha»)")
        if fim.get("atalho"):
            etapas.contar("resolvidos pelo caminho rápido")
    return etapas


# --- 2. depois: o caminho rápido com o código de verdade ---------------------------------------
@dataclass
class _JanelasDeMentira:
    """Duas janelas de app, o Brave na frente do principal e o Jarvis ativo no outro monitor."""

    fechadas: list[str] = field(default_factory=list)

    def listar(self) -> list[Any]:
        estado = self.estado()
        return list(estado.janelas) if estado is not None else []

    def estado(self) -> Any:
        from jarvis.executor.janelas import EstadoDasJanelas, JanelaDoSistema, Monitor

        brave = JanelaDoSistema(
            "{11111111-1111-1111-1111-111111111111}",
            "YouTube - Brave",
            "brave-browser",
            4001,
            monitor="DP-1",
            principal=True,
            na_frente=True,
        )
        discord = JanelaDoSistema(
            "{22222222-2222-2222-2222-222222222222}",
            "Discord",
            "discord",
            4002,
            ativa=True,
            monitor="HDMI-A-1",
            na_frente=True,
        )
        janelas = tuple(j for j in (brave, discord) if j.id not in self.fechadas)
        return EstadoDasJanelas(
            janelas, (Monitor("DP-1", True), Monitor("HDMI-A-1", False)), "HDMI-A-1"
        )

    def ativar(self, janela_id: str) -> bool:
        return True

    def fechar(self, janela_id: str) -> bool:
        self.fechadas.append(janela_id)
        return True


class _ExtensaoDeMentira:
    """Responde como a extensão confere a navegação (a aba saiu do lugar e carregou), na hora."""

    def __init__(self) -> None:
        self.abas: dict[int, str] = {7: "https://www.google.com/"}

    def chamar(self, pedido: Any, navegador: str = "") -> dict[str, Any]:
        ok: dict[str, Any] = {"id": pedido.id, "ok": True}
        p = pedido.params

        def aba(tab_id: int) -> dict[str, Any]:
            return {"id": tab_id, "janelaId": 1, "ativa": True, "url": self.abas[tab_id]}

        if pedido.method == "tabs.list":
            return ok | {"result": {"abas": [aba(i) for i in self.abas]}}
        if pedido.method == "tabs.current":
            return ok | {"result": {"aba": aba(int(p.get("tabId") or 7))}}
        if pedido.method in ("tabs.open", "tabs.navigate"):
            tab_id = int(p.get("tabId") or max(self.abas) + 1)
            self.abas[tab_id] = str(p["url"])
            pagina = {"url": p["url"], "titulo": "Página"}
            feito = {"aba": aba(tab_id), "comecou": True, "carregou": True, "pagina": pagina}
            return ok | {"result": feito | {"janela": "dono", "visivel": True}}
        if pedido.method == "tabs.show":
            return ok | {"result": {"aba": aba(int(p["tabId"])), "visivel": True}}
        if pedido.method == "windows.focused":
            return ok | {"result": {"janelaId": 1, "abaAtivaId": 7}}
        return ok | {"result": {}}


def medir_o_caminho_rapido(n: int) -> dict[str, dict[str, list[float]]]:
    """Cada comando `n` vezes, num cérebro com o caminho rápido ligado e um motor que não pode ser
    chamado (se fosse, a medida seria a de antes)."""
    from jarvis.executor.ferramentas import ExecutorDeFerramentas
    from jarvis.executor.lancador import App, RegistroDeApps
    from jarvis.executor.nativas import Nativas
    from jarvis.navegador.cliente import ClienteDoNavegador
    from jarvis.navegador.ferramentas import CorposDoNavegador
    from jarvis.politica.auditoria import LogDeAuditoria
    from jarvis.politica.catalogo import carregar_catalogo
    from jarvis.politica.modos import Modo
    from jarvis.politica.pdp import Pdp
    from jarvis.s2.cerebro import Cerebro
    from jarvis.s2.motor_roteirizado import MotorRoteirizado

    def proibido(_contexto: object) -> str:
        raise AssertionError("o motor foi chamado: não é o caminho rápido")

    discord = App(
        id="discord",
        nome="Discord",
        nomes=("Discord", "discord"),
        argv=("/usr/bin/discord",),
        arquivo=Path("/usr/share/applications/discord.desktop"),
        exec_nome="discord",
    )
    comandos = (
        "abre o Discord",
        "fecha o Discord",
        "o que está em foco?",
        "abre o YouTube",
        "pesquisa vídeos de gatos no YouTube",
    )
    medidas: dict[str, dict[str, list[float]]] = {}
    with tempfile.TemporaryDirectory(prefix="jv-") as pasta:
        raiz = Path(pasta)
        lar = raiz / "casa"
        lar.mkdir()
        with LogDeAuditoria(raiz / "auditoria.sqlite") as auditoria:
            pdp = Pdp(
                catalogo=carregar_catalogo(),
                lar=lar,
                auditoria=auditoria,
                modo=Modo.PADRAO,
                pasta_do_jarvis=raiz / "area",
                apps_autorizados=frozenset({"discord"}),
            )
            executor = ExecutorDeFerramentas(
                pdp=pdp,
                lar=lar,
                registro_de_apps=RegistroDeApps(
                    autorizados={"discord": discord},
                    instalados=frozenset({"discord"}),
                    catalogo={"discord": discord},
                ),
                lancar_app=lambda _app: 4242,
                navegador=CorposDoNavegador(ClienteDoNavegador(_ExtensaoDeMentira())),
            )
            executor.preparar()
            for fala in comandos:
                for _ in range(n):
                    executor.nativas = Nativas(lar=lar, janelas=_JanelasDeMentira())
                    cerebro = Cerebro(
                        motor=MotorRoteirizado(resposta=proibido),
                        ferramentas=executor,
                        caminho_rapido=True,
                    )
                    primeira: list[float] = []
                    comeco = time.perf_counter()

                    def publicar(
                        pedaco: dict[str, object],
                        primeira: list[float] = primeira,
                        comeco: float = comeco,
                    ) -> None:
                        if pedaco.get("text") and not primeira:
                            primeira.append((time.perf_counter() - comeco) * 1000.0)

                    resposta = cerebro.responder(fala, epoch=1, publicar=publicar)
                    total = (time.perf_counter() - comeco) * 1000.0
                    if resposta.motor_chamado or not primeira:
                        raise AssertionError(f"«{fala}» não foi pelo caminho rápido")
                    etapas = medidas.setdefault(fala, {})
                    etapas.setdefault("1ª ferramenta", []).append(
                        resposta.ms_ate_primeira_ferramenta or 0.0
                    )
                    etapas.setdefault("1ª fala", []).append(primeira[0])
                    etapas.setdefault("turno inteiro", []).append(total)
    return medidas


# --- 3. rede ---------------------------------------------------------------------------------
SERVICOS: Final = (
    ("Groq", "https://api.groq.com/"),
    ("ElevenLabs", "https://api.elevenlabs.io/health"),
)
"""Endereços que respondem 200 sem autenticação: um 4xx fecha a conexão (o pool só guarda a que
terminou bem), e a medida da reaproveitada viraria a de uma conexão nova."""


def medir_a_rede(n: int) -> dict[str, dict[str, list[float]]]:
    """GET sem autenticação num endereço público do serviço; o tempo é até o corpo chegar."""
    import urllib.error
    import urllib.request

    from jarvis.voz.nuvem import ConexoesPersistentes

    def um_get(conexoes: ConexoesPersistentes, url: str) -> float:
        pedido = urllib.request.Request(url, method="GET")  # noqa: S310 — https fixo da tabela
        pedido.add_header("User-Agent", "jarvis-medicao")
        comeco = time.perf_counter()
        try:
            with conexoes(pedido, timeout=10.0) as resposta:
                while resposta.read(8192):
                    pass
        except urllib.error.HTTPError:
            pass
        return (time.perf_counter() - comeco) * 1000.0

    medidas: dict[str, dict[str, list[float]]] = {}
    for nome, url in SERVICOS:
        novas, reaproveitadas, aquecidas = [], [], []
        for _ in range(n):
            nova = ConexoesPersistentes()
            novas.append(um_get(nova, url))
            reaproveitadas.append(um_get(nova, url))
            nova.fechar()
            quente = ConexoesPersistentes()
            quente.aquecer(url)
            aquecidas.append(um_get(quente, url))
            quente.fechar()
        medidas[nome] = {
            "conexão nova (antes)": novas,
            "conexão reaproveitada (depois)": reaproveitadas,
            "1º pedido com aquecer (depois)": aquecidas,
        }
    return medidas


# --- 4. a máquina ------------------------------------------------------------------------------
def gpu() -> str:
    programa = shutil.which("nvidia-smi")
    if programa is None:
        return "nenhuma (sem nvidia-smi)"
    saida = subprocess.run(
        [programa, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    return saida.stdout.strip() or "?"


def threads_do_embedding(vezes: int = 10) -> dict[int, list[float]]:
    """A consulta da memória (o e5 em ONNX) antes de cada turno, com 2 e 4 threads."""
    from jarvis.memoryd.embedding import EmbedderE5

    textos = (
        "abre o canal do primo rico no youtube",
        "qual janela está em foco",
        "fecha o discord",
    )
    medidas: dict[int, list[float]] = {}
    for threads in (2, 4):
        try:
            embedder = EmbedderE5(threads=threads)
            embedder.abrir()
        except Exception:  # sem o modelo baixado: a linha diz que não mediu
            return {}
        for texto in textos:
            embedder.embed([texto], "query")
        tempos = []
        for _ in range(vezes):
            for texto in textos:
                comeco = time.perf_counter()
                embedder.embed([texto], "query")
                tempos.append((time.perf_counter() - comeco) * 1000.0)
        medidas[threads] = tempos
    return medidas


# --- o relatório -------------------------------------------------------------------------------
def _linha(nome: str, valores: Sequence[float]) -> str:
    if not valores:
        return f"| {nome} | 0 | — | — |"
    return (
        f"| {nome} | {len(valores)} | {statistics.median(valores):.0f} ms | "
        f"{percentil(list(valores), 95):.0f} ms |"
    )


def _p50(valores: Sequence[float]) -> float:
    return statistics.median(valores) if valores else 0.0


def _resumo(antes: Etapas, depois: Mapping[str, Mapping[str, list[float]]]) -> list[str]:
    """O caminho de um pedido típico, antes e depois — composto das etapas medidas (o nosso tempo,
    medido aqui, mais o da ferramenta e o do TTS, medidos na trilha do dono)."""
    tts = _p50(antes.valores.get("TTS: da 1ª fala ao 1º áudio (ms)", []))
    fala_antes = _p50(antes.valores.get("1ª fala (ms)", []))
    audio_antes = _p50(antes.valores.get("1º áudio (ms)", []))
    site_antes = _p50(antes.valores.get("pedido de site: até a 1ª página aberta (ms)", []))
    navegar = [
        v for v in antes.valores.get("ferramenta browser.navigate (ms)", []) if v >= 100
    ]  # as que navegaram de verdade (as de 2–3 ms são o id velho, com erro)
    linhas = [
        "",
        "## 5. O pedido típico, antes e depois (p50)",
        "",
        "Depois = o nosso tempo (tabela 2) + a ferramenta + o TTS, os dois da trilha do dono "
        "(tabela 1). Composição das etapas medidas, não uma medida de ponta a ponta no desktop "
        "dele.",
        "",
        "| pedido | antes: 1ª fala | antes: 1º áudio | depois: 1ª fala | depois: 1º áudio |",
        "|---|---:|---:|---:|---:|",
    ]
    ferramentas = {
        "abre o Discord": _p50(antes.valores.get("ferramenta apps.launch (ms)", [])),
        "abre o YouTube": _p50(navegar),
        "pesquisa vídeos de gatos no YouTube": _p50(navegar),
        "o que está em foco?": 5.0,  # a leitura do KWin (docs/medicoes/foco-kwin-virtual.md)
    }
    for fala, ferramenta in ferramentas.items():
        nosso = _p50(depois.get(fala, {}).get("1ª fala", []))
        if not nosso:
            continue
        linhas.append(
            f"| «{fala}» | {fala_antes:.0f} ms | {audio_antes:.0f} ms | "
            f"{nosso + ferramenta:.0f} ms | {nosso + ferramenta + tts:.0f} ms |"
        )
    if site_antes:
        linhas += [
            "",
            f"Pedido de site, até a 1ª página aberta: antes **{site_antes:.0f} ms** (p50 da "
            "trilha: o motor planejava, buscava numa aba escondida e errava o id da aba); depois, "
            f"o 1º passo é do código: ~{_p50(navegar):.0f} ms (a navegação da extensão).",
            "",
            "O `window.close` da trilha (10–22 s) inclui a espera pelo «sim» do dono — fechar a "
            "janela do navegador pergunta (ADR-0042): não é tempo do código.",
        ]
    return linhas


def markdown(
    antes: Etapas,
    depois: Mapping[str, Mapping[str, list[float]]],
    rede: Mapping[str, Mapping[str, list[float]]],
    embedding: Mapping[int, list[float]],
    *,
    desde: str,
) -> str:
    maquina = hardware()
    linhas = [
        "# Velocidade do pedido, por etapa: antes e depois (ADR-0045)",
        "",
        f"**Gerado por** `tools/medir_velocidade.py` (não editar à mão). **Data:** "
        f"{datetime.now():%Y-%m-%d}. **Máquina:** {maquina['cpu']}, {maquina['nucleos']} fios, "
        f"{maquina['memoria']} de RAM, GPU {gpu()}; {maquina['plataforma']}, Python "
        f"{maquina['python']}.",
        "",
        "## 1. Antes — a trilha do dono (turnos de verdade, só metadados)",
        "",
        f"Turnos com método ou ferramenta desde {desde}: **{antes.contagens.get('turnos', 0)}**. "
        "Motor `claude -p` (o modelo padrão da conta), extensão no Brave, ASR da Groq e voz da "
        "ElevenLabs. O ASR e o contexto só aparecem nos turnos gravados depois desta medição "
        "(campos novos da trilha).",
        "",
        "| etapa | n | p50 | p95 |",
        "|---|---:|---:|---:|",
    ]
    ordem = (
        "fala do dono (ms)",
        "ASR (ms)",
        "contexto do cérebro (ms)",
        "1º token do motor (ms)",
        "1ª ferramenta (ms desde o turno)",
        "1ª fala (ms)",
        "1º áudio (ms)",
        "TTS: da 1ª fala ao 1º áudio (ms)",
        "pedido de site: até a 1ª página aberta (ms)",
    )
    for etapa in ordem:
        linhas.append(_linha(etapa, antes.valores.get(etapa, [])))
    for etapa in sorted(k for k in antes.valores if k.startswith("ferramenta ")):
        linhas.append(_linha(etapa, antes.valores[etapa]))
    contagens = [
        f"{nome}: {quantos}"
        for nome, quantos in sorted(antes.contagens.items())
        if nome != "turnos"
    ]
    if contagens:
        linhas += ["", "Contagens: " + " · ".join(contagens) + "."]
    linhas += [
        "",
        "## 2. Depois — o caminho rápido, com o código de verdade e sem LLM",
        "",
        "Cérebro, executor, PDP e auditoria em SQLite (numa pasta temporária); o motor que não "
        "pode "
        "ser chamado (o teste quebra se for). As ferramentas respondem na hora: este é o tempo que "
        "é **nosso**. No desktop do dono some-se o tempo da ferramenta (tabela 1: o `apps.launch`, "
        "a extensão) e, para a fala, o TTS.",
        "",
        "| comando | etapa | n | p50 | p95 |",
        "|---|---|---:|---:|---:|",
    ]
    for fala, etapas in depois.items():
        for etapa, valores in etapas.items():
            linhas.append(
                f"| «{fala}» " + _linha(etapa, valores).removeprefix("| ").replace("| ", "| ", 1)
            )
    if rede:
        linhas += [
            "",
            "## 3. Rede — conexão nova × reaproveitada (GET sem autenticação, sem chave)",
            "",
            "| serviço | etapa | n | p50 | p95 |",
            "|---|---|---:|---:|---:|",
        ]
        for servico, etapas in rede.items():
            for etapa, valores in etapas.items():
                linhas.append(f"| {servico} " + _linha(etapa, valores).replace("| ", "| ", 1))
    if embedding:
        linhas += [
            "",
            "## 4. Escala pela máquina — a consulta da memória antes de cada turno",
            "",
            "| threads do embedding (e5, ONNX, CPU) | n | p50 | p95 |",
            "|---|---:|---:|---:|",
        ]
        for threads, valores in embedding.items():
            linhas.append(_linha(f"{threads}", valores))
        linhas += [
            "",
            "Com 12 fios o Jarvis passa a usar 4 (`threads_da_maquina`: piso 2, teto 4, "
            "`JARVIS_THREADS_DA_MEMORIA` manda). O Whisper local (`small`, int8) leva ~1,4 s "
            "por fala de ~2,2 s na CPU com 4 ou 6 threads (medido em 2026-10-21 com o corpus); "
            "na GPU ele não carrega sem a `libcublas.so.12` (as bibliotecas CUDA da NVIDIA, "
            "licença própria) — decisão do dono. Até lá, a Groq é o ASR mais rápido aqui.",
        ]
    linhas += _resumo(antes, depois)
    return "\n".join(linhas) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    opcoes = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opcoes.add_argument("--trilha", type=Path, default=TRILHA_PADRAO)
    opcoes.add_argument("--desde", default="", help="AAAA-MM-DD: só turnos a partir desse dia")
    opcoes.add_argument("--n", type=int, default=50)
    opcoes.add_argument("--rede", action="store_true", help="mede a rede (GET sem chave)")
    opcoes.add_argument("--saida", type=Path)
    args = opcoes.parse_args(argv)
    desde = datetime.strptime(args.desde, "%Y-%m-%d").timestamp() if args.desde else 0.0
    antes = etapas_da_trilha(_eventos(args.trilha), desde)
    depois = medir_o_caminho_rapido(args.n)
    rede = medir_a_rede(max(5, args.n // 5)) if args.rede else {}
    embedding = threads_do_embedding()
    texto = markdown(antes, depois, rede, embedding, desde=args.desde or "o começo da trilha")
    if args.saida is not None:
        args.saida.write_text(texto, encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
