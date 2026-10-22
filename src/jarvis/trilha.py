"""A trilha de diagnóstico do turno: o que o Jarvis fez, quanto levou e por que perguntou.

Pedido do dono (2026-10-20, depois de testar o app): para melhorar o Jarvis é preciso ver o que
ele fez em cada turno — que ferramentas chamou, quando cada uma começou e terminou, quanto levou,
o que o PDP, o Jev e as pendências decidiram, o motivo de cada pedido de permissão e os erros de
ferramenta e de seletor.

Um JSONL local, rotativo (`turnos.jsonl`, `.1`, `.2`…), **só de metadados**. O que entra não é
decidido por lista de proibições (frágil: o que não está nela passa), e sim por **allowlist**:
`EVENTOS` diz quais campos cada tipo de evento pode ter e `CAMPOS` diz a forma de cada um
(número, booleano, código, rótulo curto, motivo escrito pelo próprio código, nomes de
argumento). Campo fora da allowlist não é gravado — só o **nome** dele vai para `campos_fora`,
para que a omissão apareça em vez de ficar escondida; valor que não cabe na forma vira
`[fora_da_forma]`. O `motivo` de ferramenta, de permissão e de método é um **código** da
allowlist `CAUSAS` (`envia_formulario`, `elemento_sem_nome`…), nunca a frase: a frase da pergunta
ao dono cita o rótulo que a página dá ao elemento. Nos textos que sobram (o erro do turno e a
razão do Jev, que o nosso código escreve) ainda passa a redação de segredos do projeto, a URL
fica reduzida a esquema e host, o caminho a `/…`, e o resto é cortado. Nunca vai texto do dono,
texto ou DOM de página, resultado de ferramenta, valor de argumento nem áudio. Nada sai da
máquina.

Limites (documentados em `docs/COMO-TESTAR.md` §0.10): pasta `0700` e arquivo `0600`, até
`TAMANHO_MAXIMO` por arquivo e `COPIAS` cópias antigas, e retenção por idade — arquivo sem
toque há mais de `DIAS_DE_RETENCAO` dias sai do disco. O `jarvis-voz --diagnostico` lê o último
turno daqui (`resumo_do_ultimo_turno`) e mostra esses limites (`limites`).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from enum import Enum, auto
from pathlib import Path
from typing import Any, Final

from jarvis.memoryd.importacao import CAMINHO, redigir

ARQUIVO: Final = "turnos.jsonl"
TAMANHO_MAXIMO: Final = 512 * 1024
COPIAS: Final = 3
"""Até ~2 MB no total: o arquivo vivo e três antigos."""
DIAS_DE_RETENCAO: Final = 7
"""Retenção por idade: arquivo sem toque há mais dias que isto é apagado (poda no primeiro
evento da sessão e a cada volta do arquivo)."""
SEGUNDOS_POR_DIA: Final = 86_400.0
PERMISSAO_DA_PASTA: Final = 0o700
PERMISSAO_DO_ARQUIVO: Final = 0o600
"""Só o dono lê a trilha: a pasta e o arquivo nascem (e são corrigidos) sem grupo nem outros."""
CARACTERES_POR_TEXTO: Final = 160
CARACTERES_POR_ROTULO: Final = 48
CODIGO_NO_MOTIVO: Final = r"^a página não deixou \(([a-z][a-z_]{2,40})\)"
"""O código da extensão que o corpo das browser.* põe entre parênteses no **começo** da frase:
"a página não deixou (alvo_ausente): …". Só ali — no meio da frase pode estar o rótulo que a
página dá ao elemento, e um rótulo "(algo)" não vira código."""

FORA_DA_FORMA: Final = "[fora_da_forma]"
"""Valor que não cabe na forma do campo: o campo fica, com esta marca em vez do valor."""
URL: Final = re.compile(r"\b([a-z][a-z0-9+.-]*)://([^\s/?#]{1,80})\S*")
"""URL no texto vira `esquema://host/…`: o caminho e a consulta podem ser dado privado."""
SO_CODIGO: Final = re.compile(r"^[\w.:/-]{0,64}$")


class Forma(Enum):
    """A forma de um campo da trilha — é ela que decide o que sobra do valor."""

    NUMERO = auto()
    """`int`/`float`/`None`: vai como está (float arredondado)."""
    BOOLEANO = auto()
    """`bool`/`None`."""
    CODIGO = auto()
    """Código curto e estável do nosso código (`alvo_ausente`, `browser.click`, `ok`)."""
    ROTULO = auto()
    """Rótulo de decisão, com espaço mas curto ("não chegou ao PDP")."""
    MOTIVO = auto()
    """Frase que o **nosso** código escreve: redigida, com URL e caminho reduzidos, e cortada."""
    CAUSA = auto()
    """Código de motivo da allowlist `CAUSAS` (vários, unidos por `+`). Fora dela, a marca."""
    CHAVES = auto()
    """Nomes de argumento — nunca os valores."""


CAMPOS: Final[Mapping[str, Forma]] = {
    "argumentos": Forma.CHAVES,
    "aviso": Forma.CODIGO,
    "cancelado": Forma.BOOLEANO,
    "caracteres_de_raciocinio": Forma.NUMERO,
    "caracteres_do_pedido": Forma.NUMERO,
    "caracteres_falados": Forma.NUMERO,
    "caracteres_so_na_tela": Forma.NUMERO,
    "codigo": Forma.CODIGO,
    "contraste_db": Forma.NUMERO,
    "de_fora": Forma.NUMERO,
    "decisao": Forma.CODIGO,
    "epoch": Forma.NUMERO,
    "erro": Forma.MOTIVO,
    "etapa": Forma.CODIGO,
    "fase": Forma.CODIGO,
    "ferramentas": Forma.NUMERO,
    "fim": Forma.CODIGO,
    "jev": Forma.MOTIVO,
    "logprob": Forma.NUMERO,
    "maior_fala_ms": Forma.NUMERO,
    "metodo": Forma.CODIGO,
    "modo": Forma.CODIGO,
    "motivo": Forma.CAUSA,
    "motor": Forma.CODIGO,
    "ms": Forma.NUMERO,
    "ms_primeira_fala": Forma.NUMERO,
    "ms_primeiro_audio": Forma.NUMERO,
    "ms_primeiro_token": Forma.NUMERO,
    "ms_total": Forma.NUMERO,
    "narracao_retida": Forma.NUMERO,
    "objetivo": Forma.CODIGO,
    "origem": Forma.CODIGO,
    "pdp": Forma.ROTULO,
    "raciocinio_descartado": Forma.NUMERO,
    "resposta": Forma.CODIGO,
    "resultados_podados": Forma.NUMERO,
    "sem_fala": Forma.NUMERO,
    "status": Forma.CODIGO,
    "tool_id": Forma.CODIGO,
}
"""A allowlist de campos: nome → forma. Mesmo nome, mesma forma em qualquer evento. Campo que
não está aqui não é gravado, e o nome dele aparece em `campos_fora`."""

EVENTOS: Final[Mapping[str, frozenset[str]]] = {
    "turno.inicio": frozenset({"motor", "epoch", "caracteres_do_pedido"}),
    "turno.fim": frozenset(
        {
            "fim",
            "cancelado",
            "ms_primeiro_token",
            "ms_primeira_fala",
            "ms_primeiro_audio",
            "ms_total",
            "ferramentas",
            "caracteres_falados",
            "caracteres_de_raciocinio",
            "raciocinio_descartado",
            "narracao_retida",
            "caracteres_so_na_tela",
            "resultados_podados",
            "objetivo",
            "erro",
        }
    ),
    "ferramenta.inicio": frozenset({"tool_id", "argumentos", "pdp", "fase"}),
    "ferramenta": frozenset(
        {"tool_id", "argumentos", "status", "pdp", "ms", "motivo", "codigo", "aviso", "fase"}
    ),
    "portao": frozenset({"tool_id", "pdp", "jev", "decisao", "ms"}),
    "permissao": frozenset({"tool_id", "origem", "motivo", "resposta"}),
    "metodo": frozenset({"metodo", "motivo", "de_fora"}),
    # Interromper por voz (ADR-0040): o modo de escuta, o que a vigia fez, por quê e em quantos ms
    # de trecho — nunca o que o dono disse nem o que o ASR ouviu.
    "interrupcao": frozenset({"modo", "decisao", "motivo", "ms"}),
    # Ruído que não virou pedido (ADR-0043): em que etapa caiu (o portão do trecho ou o filtro da
    # transcrição), o código do motivo e os números que decidiram — nunca o áudio nem o texto.
    "ruido": frozenset(
        {"etapa", "motivo", "modo", "ms", "maior_fala_ms", "contraste_db", "sem_fala", "logprob"}
    ),
}
"""Que campos cada evento pode ter. Tipo de evento fora daqui grava só o cabeçalho e os nomes
dos campos que vieram — assim um evento novo aparece na trilha sem levar valor nenhum consigo."""

CAMPOS_BASE: Final = frozenset({"t", "turno", "evento", "campos_fora"})

SEM_CAUSA: Final = "sem_codigo"
"""Resultado que não foi ok e não disse a causa: o código genérico, nunca a frase."""
CAUSAS: Final[frozenset[str]] = frozenset(
    {
        SEM_CAUSA,
        # quem pediu o sim
        "confirmacao_do_pdp",
        "portao_pediu_permissao",
        # o risco do que está sob o clique (`jarvis.navegador.risco`)
        "categoria_do_site",
        "envia_formulario",
        "formulario_sensivel",
        "palavra_de_risco",
        "elemento_sem_nome",
        "enter_envia",
        "destino_externo",
        "dado_do_dono_para_fora",
        "turno_contaminado",
        "segredo_do_dono",
        # a janela em foco (`jarvis.entrada.controle`)
        "categoria_da_janela",
        # a ferramenta que não terminou ok (`jarvis.executor.ferramentas`, `jarvis.s2`)
        "metodo_de_fora",
        "ferramenta_desligada",
        "fora_do_contrato",
        "argumento_recusado",
        "app_ambiguo",
        "dono_nao_confirmou",
        "pdp_negou",
        "interrompido",
        "acao_recusada",
        "erro_da_ferramenta",
        "portao_negou",
        "esperando_o_dono",
        "pergunta_ocupada",
        "portao_falhou",
        # o método do pedido (`jarvis.politica.metodo`)
        "pede_teclado_ou_mouse",
        "pede_terminal",
        "abre_o_navegador",
        "site_sem_automacao",
        "cita_site",
        "cita_site_sem_extensao",
        "busca_generica",
        "pesquisa_no_navegador",
        "cita_app",
        "pede_sistema",
        "pede_memoria",
        "pedido_misto",
        "sem_metodo_especifico",
        "encerra_o_jarvis",
        "fecha_janela",
        "encerra_app",
        # fechar a janela × encerrar o app (`jarvis.executor.fechar`, ADR-0042)
        "alvo_ausente",
        "alvo_ambiguo",
        "alvo_protegido",
        "sem_janelas",
        "sem_suporte",
        # a vigia que ouve o dono enquanto o Jarvis fala (`jarvis.voz.interrupcao`)
        "suspeita",
        "palavra_de_ativacao",
        "ordem_de_parar",
        "enderecada",
        "eco_do_jarvis",
        "sem_fala",
        "sem_chamada",
        "nao_era_comigo",
        "prazo_da_pausa",
        # o ruído que não virou pedido (`jarvis.voz.ruido`, ADR-0043)
        "impulso",
        "fundo",
        "so_simbolos",
        "alucinacao",
        "repeticao",
        "eco_da_dica",
        "incerto_curto",
        "sim_incerto",
    }
)
"""A allowlist do `motivo`: códigos que o nosso código escolhe pelo caminho que tomou. Código novo
entra aqui, ou a trilha grava a marca no lugar dele."""


def texto_seguro(valor: object, limite: int) -> str:
    """Redige o segredo, reduz URL a `esquema://host/…` e caminho a `/…`, e corta no limite."""
    redigido = redigir(str(valor)).texto
    sem_url = URL.sub(r"\1://\2/…", redigido)
    sem_caminho = CAMINHO.sub("/…", sem_url)
    texto = " ".join(sem_caminho.split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


def na_forma(forma: Forma, valor: object) -> object:
    """O que sobra do valor na forma do campo; o que não cabe vira `FORA_DA_FORMA`."""
    if forma is Forma.NUMERO:
        if valor is None or (isinstance(valor, int | float) and not isinstance(valor, bool)):
            return round(valor, 3) if isinstance(valor, float) else valor
        return FORA_DA_FORMA
    if forma is Forma.BOOLEANO:
        return valor if valor is None or isinstance(valor, bool) else FORA_DA_FORMA
    if forma is Forma.CHAVES:
        if not isinstance(valor, list | tuple):
            return FORA_DA_FORMA
        return [na_forma(Forma.CODIGO, chave) for chave in list(valor)[:20]]
    if forma is Forma.CODIGO:
        texto = str(valor)
        return texto if SO_CODIGO.match(texto) else FORA_DA_FORMA
    if forma is Forma.CAUSA:
        texto = str(valor)
        if not texto or all(parte in CAUSAS for parte in texto.split("+")):
            return texto
        return FORA_DA_FORMA
    limite = CARACTERES_POR_ROTULO if forma is Forma.ROTULO else CARACTERES_POR_TEXTO
    return texto_seguro(valor, limite)


def pela_allowlist(tipo: str, campos: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    """Os campos que este evento pode ter, na forma de cada um, e os nomes dos que ficaram fora."""
    permitidos = EVENTOS.get(tipo, frozenset())
    dentro: dict[str, object] = {}
    fora: list[str] = []
    for nome, valor in campos.items():
        forma = CAMPOS.get(nome)
        if forma is None or nome not in permitidos or nome in CAMPOS_BASE:
            fora.append(str(na_forma(Forma.CODIGO, nome)))
            continue
        dentro[nome] = na_forma(forma, valor)
    return dentro, sorted(fora)


class TrilhaDeDiagnostico:
    """Escreve eventos de metadados do turno; segura para várias linhas de execução."""

    def __init__(
        self,
        pasta: Path,
        *,
        tamanho_maximo: int = TAMANHO_MAXIMO,
        copias: int = COPIAS,
        dias_de_retencao: int = DIAS_DE_RETENCAO,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self.pasta = pasta
        self._tamanho_maximo = tamanho_maximo
        self._copias = copias
        self._dias_de_retencao = dias_de_retencao
        self._relogio = relogio
        self._trava = threading.Lock()
        self._preparada = False
        self.turno = ""
        """O turno corrente: os eventos sem `turno` explícito ficam nele."""

    @property
    def arquivo(self) -> Path:
        return self.pasta / ARQUIVO

    def novo_turno(self, turno: str, **campos: object) -> None:
        self.turno = turno
        self.evento("turno.inicio", **campos)

    def evento(self, tipo: str, **campos: object) -> None:
        """Um evento. Falha de disco não derruba o turno: a trilha é ajuda, não requisito."""
        turno = campos.pop("turno", None) or self.turno
        dentro, fora = pela_allowlist(tipo, campos)
        registro: dict[str, object] = {
            "t": round(self._relogio(), 3),
            "turno": na_forma(Forma.CODIGO, turno),
            "evento": tipo if tipo in EVENTOS else na_forma(Forma.CODIGO, tipo),
        }
        registro.update(dentro)
        if fora:
            registro["campos_fora"] = fora
        linha = json.dumps(registro, ensure_ascii=False) + "\n"
        with self._trava:
            try:
                self._preparar()
                self.pasta.mkdir(parents=True, exist_ok=True)
                self._girar_se_preciso(len(linha.encode("utf-8")))
                descritor = os.open(
                    self.arquivo,
                    os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                    PERMISSAO_DO_ARQUIVO,
                )
                with os.fdopen(descritor, "a", encoding="utf-8") as saida:
                    saida.write(linha)
            except OSError:
                return

    def _preparar(self) -> None:
        """Uma vez por instância: pasta e arquivos só do dono, e a poda da retenção."""
        if self._preparada:
            return
        self._preparada = True
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.pasta.chmod(PERMISSAO_DA_PASTA)
        self._podar()
        for arquivo in self._arquivos():
            try:
                arquivo.chmod(PERMISSAO_DO_ARQUIVO)
            except OSError:
                continue

    def _arquivos(self) -> list[Path]:
        return [self.arquivo] + [
            self.pasta / f"{ARQUIVO}.{indice}" for indice in range(1, self._copias + 1)
        ]

    def _podar(self) -> None:
        """Retenção por idade: arquivo sem toque há mais de `dias_de_retencao` sai do disco."""
        limite = self._relogio() - self._dias_de_retencao * SEGUNDOS_POR_DIA
        for arquivo in self._arquivos():
            try:
                if arquivo.stat().st_mtime < limite:
                    arquivo.unlink(missing_ok=True)
            except OSError:
                continue

    def _girar_se_preciso(self, acrescimo: int) -> None:
        try:
            atual = self.arquivo.stat().st_size
        except FileNotFoundError:
            return
        if atual + acrescimo <= self._tamanho_maximo:
            return
        mais_velho = self.pasta / f"{ARQUIVO}.{self._copias}"
        mais_velho.unlink(missing_ok=True)
        for indice in range(self._copias - 1, 0, -1):
            antigo = self.pasta / f"{ARQUIVO}.{indice}"
            if antigo.exists():
                antigo.rename(self.pasta / f"{ARQUIVO}.{indice + 1}")
        self.arquivo.rename(self.pasta / f"{ARQUIVO}.1")
        self._podar()


def codigo_do_motivo(motivo: str) -> str:
    """O código de erro da extensão (`alvo_ausente`) quando o motivo o traz entre parênteses."""
    achado = re.search(CODIGO_NO_MOTIVO, motivo)
    return achado.group(1) if achado is not None else ""


def _eventos(pasta: Path) -> list[dict[str, Any]]:
    """Do arquivo vivo e do `.1` (o turno pode ter começado antes da última volta)."""
    eventos: list[dict[str, Any]] = []
    for arquivo in (pasta / f"{ARQUIVO}.1", pasta / ARQUIVO):
        try:
            linhas = arquivo.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for linha in linhas:
            try:
                dado = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(dado, dict):
                eventos.append(dado)
    return eventos


def eventos_do_ultimo_turno(pasta: Path) -> list[dict[str, Any]]:
    eventos = _eventos(pasta)
    inicios = [e for e in eventos if e.get("evento") == "turno.inicio"]
    if not inicios:
        return []
    turno = inicios[-1].get("turno")
    return [e for e in eventos if e.get("turno") == turno]


def ruidos_descartados(pasta: Path) -> dict[str, int]:
    """Quantos trechos de ruído não viraram pedido, por motivo, no arquivo vivo da trilha e no
    anterior (ADR-0043). É o que o `--diagnostico` mostra para calibrar o filtro na máquina do
    dono — só a contagem: o evento nunca leva o áudio nem o texto."""
    contagem: dict[str, int] = {}
    for evento in _eventos(pasta):
        if evento.get("evento") == "ruido":
            motivo = str(evento.get("motivo") or SEM_CAUSA)
            contagem[motivo] = contagem.get(motivo, 0) + 1
    return dict(sorted(contagem.items(), key=lambda item: (-item[1], item[0])))


def _ms(valor: object) -> str:
    return f"{float(valor):.0f} ms" if isinstance(valor, int | float) else "?"


def limites(pasta: Path) -> list[str]:
    """Onde a trilha mora e até onde cresce — o `--diagnostico` mostra antes do resumo."""
    try:
        tamanho = f"{pasta.joinpath(ARQUIVO).stat().st_size / 1024:.0f} KiB"
    except OSError:
        tamanho = "ainda não existe"
    total = TAMANHO_MAXIMO * (COPIAS + 1) / (1024 * 1024)
    return [
        f"  arquivo {pasta / ARQUIVO} ({tamanho}; pasta 0700, arquivo 0600, nada sai da máquina)",
        f"  rotação: {TAMANHO_MAXIMO // 1024} KiB por arquivo e {COPIAS} cópias "
        f"(~{total:.0f} MB no total) · retenção: {DIAS_DE_RETENCAO} dias sem toque e o arquivo sai",
    ]


def resumo_do_ultimo_turno(pasta: Path) -> list[str]:
    """O último turno em linhas curtas, para o `jarvis-voz --diagnostico`.

    Honesto por construção: diz quando não há turno, quando o turno não teve linha de fim e
    quando uma ferramenta começou e não terminou — em vez de mostrar um turno pela metade como
    se estivesse completo."""
    eventos = eventos_do_ultimo_turno(pasta)
    if not eventos:
        return [
            "  nenhum turno registrado (a trilha nasce no primeiro pedido; o que passa de "
            f"{DIAS_DE_RETENCAO} dias é apagado)"
        ]
    inicio = eventos[0]
    quando = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(inicio.get("t", 0))))
    linhas = [f"  turno {inicio.get('turno')} em {quando} · motor {inicio.get('motor', '?')}"]
    comecadas: list[str] = []
    for evento in eventos[1:]:
        tipo = evento.get("evento")
        if tipo == "ferramenta.inicio":
            comecadas.append(str(evento.get("tool_id")))
            continue
        if tipo == "ferramenta" and str(evento.get("tool_id")) in comecadas:
            comecadas.remove(str(evento.get("tool_id")))
        linhas.append("  " + _linha(evento))
    for tool_id in comecadas:
        linhas.append(f"  ferramenta {tool_id}: começou e não terminou (sem resultado na trilha)")
    if not any(e.get("evento") == "turno.fim" for e in eventos):
        linhas.append("  sem linha de fim: o turno foi interrompido ou o app saiu antes")
    return linhas


def _linha(evento: Mapping[str, Any]) -> str:
    tipo = evento.get("evento")
    if tipo == "ferramenta":
        detalhe = f" — {evento['motivo']}" if evento.get("motivo") else ""
        codigo = f" [{evento['codigo']}]" if evento.get("codigo") else ""
        fase = f" · fase {evento['fase']}" if evento.get("fase") else ""
        return (
            f"ferramenta {evento.get('tool_id')}: {evento.get('status')} em "
            f"{_ms(evento.get('ms'))} (PDP {evento.get('pdp', '?')}){codigo}{fase}{detalhe}"
        )
    if tipo == "portao":
        return (
            f"portão {evento.get('tool_id')}: {evento.get('decisao')} "
            f"(PDP {evento.get('pdp')}, {evento.get('jev')}, {_ms(evento.get('ms'))})"
        )
    if tipo == "metodo":
        return (
            f"método {evento.get('metodo')} ({evento.get('motivo')})"
            f" · {evento.get('de_fora', 0)} ferramenta(s) de fora"
        )
    if tipo == "permissao":
        return (
            f"pediu permissão para {evento.get('tool_id')} ({evento.get('origem')}): "
            f"{evento.get('motivo')} → {evento.get('resposta', '?')}"
        )
    if tipo == "turno.fim":
        pensou = ""
        if evento.get("caracteres_de_raciocinio") or evento.get("narracao_retida"):
            pensou = (
                f" · raciocínio {evento.get('caracteres_de_raciocinio', 0)} car. (não falado)"
                f" · narração retida {evento.get('narracao_retida', 0)}"
            )
        if evento.get("resultados_podados"):
            pensou += f" · passos antigos podados {evento['resultados_podados']}"
        if evento.get("objetivo"):
            pensou += f" · objetivo {evento['objetivo']}"
        return (
            f"fim: {evento.get('fim')} · 1ª fala {_ms(evento.get('ms_primeira_fala'))} · "
            f"1º áudio {_ms(evento.get('ms_primeiro_audio'))} · total {_ms(evento.get('ms_total'))}"
            f" · {evento.get('ferramentas', 0)} ferramenta(s){pensou}"
        )
    resto = ", ".join(f"{k}={v}" for k, v in evento.items() if k not in ("t", "turno", "evento"))
    return f"{tipo}: {resto}"


def chaves(argumentos: Mapping[str, Any] | Iterable[str]) -> list[str]:
    """Os nomes dos argumentos — nunca os valores."""
    return sorted(str(chave) for chave in argumentos)
