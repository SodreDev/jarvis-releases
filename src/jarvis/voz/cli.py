"""`jarvis-voz`: o aplicativo de teste do dono — falar, ouvir, configurar e diagnosticar.

Três entradas, e nada escondido entre elas:

    uv run jarvis-voz                  # o laço de voz
    uv run jarvis-voz --texto          # o mesmo laço, digitando (funciona sem placa de som)
    uv run jarvis-voz config           # a tela de configuração
    uv run jarvis-voz --diagnostico    # o que existe, o que falta e por quê

**Nenhuma opção aceita chave de API** — e isso é verificado, não prometido: antes de qualquer
coisa, `proibir_segredo_em_argv` recusa subir se o valor de uma das variáveis aparecer na
linha de comando, ou se um argumento tiver a forma de uma chave. `argv` é legível por outros
processos e fica no histórico do shell.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.audio_io.ambiente import VARIAVEL_BACKEND, Backend
from jarvis.audio_io.erros import ErroDeAudio
from jarvis.executor.navegadores import separar
from jarvis.navegador.cliente import TransporteUnix
from jarvis.navegador.estado import sondar
from jarvis.rede import ErroDeRede
from jarvis.trilha import limites as limites_da_trilha
from jarvis.trilha import resumo_do_ultimo_turno
from jarvis.voz.app import PASTA_DA_TRILHA, Aplicativo, AplicativoIndisponivel
from jarvis.voz.chaves import (
    VARIAVEIS,
    Chave,
    SegredoNaConfiguracao,
    SegredoNaLinhaDeComando,
    proibir_segredo_em_argv,
)
from jarvis.voz.config import (
    Configuracao,
    ConfiguracaoInvalida,
    caminho_padrao,
    ler,
)
from jarvis.voz.interface import Onde
from jarvis.voz.registro import conferir, ler_motores, motores_de
from jarvis.voz.teclado import preparado, teclado_do_ambiente
from jarvis.voz.tela_config import TelaDeConfiguracao

PASTA_DE_SESSAO: Final = "voz"


@dataclass(frozen=True, slots=True)
class Saida:
    """Código de saída com o motivo, para o `main` não espalhar `print` e `return`."""

    codigo: int
    frase: str = ""


def _raiz_de_sessao(ambiente: Mapping[str, str] | None = None) -> Path:
    """Pasta de estado desta execução: indicador de microfone, degradação, conversa."""
    import tempfile

    fonte = ambiente_ou_os(ambiente)
    base = fonte.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    try:
        raiz = Path(base) / "jarvis" / PASTA_DE_SESSAO
        raiz.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover — sem HOME gravável
        raiz = Path(tempfile.mkdtemp(prefix="jarvis-voz-"))
    return raiz


def diagnosticar(
    escrever: object = print,
    *,
    caminho: Path | None = None,
    ambiente: Mapping[str, str] | None = None,
) -> int:
    """Lista motores, chaves, dispositivos e o que falta. Nunca lê valor de chave."""
    linha = escrever if callable(escrever) else print
    alvo = caminho if caminho is not None else caminho_padrao(ambiente)

    linha("jarvis-voz — diagnóstico")
    linha("")
    linha(f"configuração: {alvo}{'' if alvo.exists() else '  (ainda não existe; usando padrões)'}")
    try:
        configuracao = ler(alvo, ambiente=ambiente)
    except (ConfiguracaoInvalida, SegredoNaConfiguracao) as erro:
        linha(f"  RECUSADA: {erro}")
        return 2
    linha(f"  ouvir: {configuracao.asr}   falar: {configuracao.tts}   responder: {configuracao.s2}")
    linha(f"  voz: {configuracao.voz}   escuta: {configuracao.escuta}")
    linha(
        f"  nuvem ligada: {', '.join(configuracao.nuvem_ligada) or 'nada (tudo fica na máquina)'}"
    )

    linha("")
    linha("navegador (extensão do Jarvis, ADR-0027) — sem falar com a extensão nem com a página:")
    fonte = ambiente_ou_os(ambiente)
    ponte = sondar(
        ligado=configuracao.navegador_controlado,
        principal=configuracao.navegador_principal,
        navegadores=separar(configuracao.navegadores),
        transporte=TransporteUnix.do_ambiente(fonte),
        home=Path(fonte["HOME"]) if fonte.get("HOME") else Path.home(),
    )
    for texto in ponte.linhas():
        linha(texto)

    linha("")
    linha(
        "último turno (trilha de diagnóstico local, só metadados — nada de fala, página ou áudio):"
    )
    pasta_da_trilha = _raiz_de_sessao(ambiente) / PASTA_DA_TRILHA
    for texto in limites_da_trilha(pasta_da_trilha):
        linha(texto)
    for texto in resumo_do_ultimo_turno(pasta_da_trilha):
        linha(texto)

    linha("")
    linha("motores registrados:")
    for motor in ler_motores():
        marca = "★" if motor.id in {configuracao.asr, configuracao.tts} else " "
        estado = "local" if motor.onde is Onde.LOCAL else "NUVEM"
        ligado = (
            ""
            if motor.onde is Onde.LOCAL
            else ("  ligado" if motor.id in configuracao.nuvem_ligada else "  desligado")
        )
        linha(f"  {marca} {motor.papel:3} {motor.id:34} [{estado}]{ligado}")

    linha("")
    linha("chaves de API (lendo só se a variável existe, nunca o valor):")
    # Dois motores da Groq usam a mesma variável: a lista é de **variáveis**, não de motores.
    for variavel in dict.fromkeys(
        m.variavel_da_chave for m in motores_de(onde=Onde.NUVEM) if m.variavel_da_chave
    ):
        origem = Chave.origem(variavel, ambiente=ambiente)
        estado = {
            "ambiente": "definida (variável de ambiente)",
            "chaveiro": "definida (chaveiro do sistema)",
        }.get(origem, "AUSENTE — guarde na janela (Configuração → Chaves de API) ou exporte")
        linha(f"  {variavel}: {estado}")

    linha("")
    linha("o que falta para cada motor rodar agora:")
    faltas = conferir(
        nuvem_ligada=configuracao.nuvem_ligada,
        ambiente=(
            *fonte.keys(),
            *(v for v in VARIAVEIS if Chave.origem(v, ambiente=ambiente) == "chaveiro"),
        ),
    )
    if not faltas:
        linha("  nada: todos os motores registrados estão prontos")
    for falta in faltas:
        linha(f"  {falta.motor}: {falta.motivo.splitlines()[0]}")

    linha("")
    linha("dispositivos de áudio:")
    try:
        from jarvis.audio_io.dispositivo import listar_dispositivos

        dispositivos = listar_dispositivos(ambiente)
    except ErroDeAudio as erro:
        linha(f"  não deu para listar: {erro}")
    else:
        if not dispositivos:
            linha("  nenhum dispositivo encontrado")
        for dispositivo in dispositivos:
            linha(f"  {dispositivo}")

    linha("")
    linha("extras opcionais:")
    for modulo, grupo, para_que in (
        ("faster_whisper", "asr", "ASR local (whisper)"),
        ("epitran", "voz", "fonemização pt-BR do TTS local"),
        ("onnxruntime", "voz", "voz do piper"),
        ("sounddevice", "dispositivo", "microfone e alto-falante reais"),
        ("lancedb", "memoria", "índice da memória (o Jarvis lembrando)"),
        ("tokenizers", "memoria", "embedding local da memória"),
        ("edge_tts", "edge", "TTS do Edge (barrado por padrão)"),
    ):
        try:
            __import__(modulo)
        except ImportError:
            linha(f"  {modulo}: falta ({para_que}) — `uv sync --group {grupo}`")
        except OSError as erro:
            # O pacote está; o que falta é biblioteca do **sistema** (o caso do PortAudio).
            # Mandar reinstalar o pacote aqui seria mandar o dono fazer o que não resolve.
            linha(f"  {modulo}: instalado, mas o sistema não tem a biblioteca — {erro}")
        else:
            linha(f"  {modulo}: ok ({para_que})")
    return 0


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="jarvis-voz",
        description="Fala e ouve o Jarvis no terminal (aplicativo de teste, ADR-0017/0018).",
        epilog="Nenhuma opção aceita chave de API: elas vêm do ambiente. Veja --diagnostico.",
    )
    analisador.add_argument(
        "comando",
        nargs="?",
        choices=("falar", "config"),
        default="falar",
        help="`falar` (padrão) abre o laço de voz; `config` abre a tela de configuração",
    )
    analisador.add_argument(
        "--texto",
        action="store_true",
        help="modo texto: digitar em vez de falar (funciona sem placa de som)",
    )
    analisador.add_argument(
        "--diagnostico",
        action="store_true",
        help="lista motores, chaves, dispositivos e o que falta",
    )
    analisador.add_argument(
        "--config", type=Path, default=None, help="outro arquivo de configuração"
    )
    analisador.add_argument("--asr", default="", help="motor de ASR só desta execução")
    analisador.add_argument("--tts", default="", help="motor de TTS só desta execução")
    analisador.add_argument(
        "--s2", default="", help="quem responde só desta execução (eco | claude)"
    )
    analisador.add_argument(
        "--turnos", type=int, default=None, help="para depois de N turnos (teste)"
    )
    analisador.add_argument(
        "--baixar-voz",
        action="store_true",
        help="baixa a voz local escolhida (diz o tamanho antes e confere o sha256 depois)",
    )
    return analisador


def baixar_voz(configuracao: Configuracao, escrever: Callable[[str], None] = print) -> int:
    """O peso não vem no pacote (ADR-0020): aqui ele é baixado, dito e conferido."""
    from jarvis.voz.modelos import ModeloRecusado, baixar, descarga_da_voz

    descarga = descarga_da_voz(configuracao.voz)
    if descarga is None:
        escrever(f"a voz {configuracao.voz!r} não está no registro de modelos")
        return 2
    escrever(descarga.frase())
    if descarga.completa:
        return 0
    ultimo = -1

    def progresso(nome: str, lidos: int, total: int) -> None:
        nonlocal ultimo
        porcento = int(100 * lidos / total) if total else 100
        if porcento != ultimo and porcento % 5 == 0:
            ultimo = porcento
            escrever(f"  {nome}: {porcento}%")

    try:
        for caminho in baixar(descarga, ao_progresso=progresso):
            escrever(f"  pronto: {caminho}")
    except (ModeloRecusado, ErroDeRede) as erro:
        escrever(f"não deu: {erro}")
        return 1
    return 0


def main(argv: Sequence[str] | None = None, *, ambiente: Mapping[str, str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    try:
        # Antes de qualquer coisa: chave em `argv` não sobe (ver `jarvis.voz.chaves`).
        proibir_segredo_em_argv([*argumentos], ambiente=ambiente)
    except SegredoNaLinhaDeComando as erro:
        print(f"recusado: {erro}", file=sys.stderr)
        return 2

    args = _analisador().parse_args(argumentos)
    caminho = args.config if args.config is not None else caminho_padrao(ambiente)

    if args.diagnostico:
        return diagnosticar(print, caminho=caminho, ambiente=ambiente)

    if args.baixar_voz:
        try:
            configuracao = ler(caminho, ambiente=ambiente)
        except (ConfiguracaoInvalida, SegredoNaConfiguracao) as erro:
            print(f"configuração recusada: {erro}", file=sys.stderr)
            return 2
        return baixar_voz(configuracao)

    if args.comando == "config":
        return TelaDeConfiguracao(caminho=caminho).rodar()

    try:
        configuracao = ler(caminho, ambiente=ambiente)
    except (ConfiguracaoInvalida, SegredoNaConfiguracao) as erro:
        print(f"configuração recusada: {erro}", file=sys.stderr)
        print("conserte com `jarvis-voz config` ou apague o arquivo.", file=sys.stderr)
        return 2
    configuracao = _com_as_opcoes_da_linha(configuracao, args)

    aplicativo = Aplicativo(
        configuracao=configuracao,
        raiz=_raiz_de_sessao(ambiente),
        ambiente=ambiente,
        teclado=teclado_do_ambiente(),
    )
    try:
        if args.texto:
            print("modo texto. Escreva e tecle Enter; `/sair` termina.")
            return aplicativo.rodar_texto(iter(sys.stdin))
        with preparado(aplicativo.teclado):
            print("falando: barra interrompe o Jarvis, `q` sai.")
            return aplicativo.rodar_audio(limite_de_turnos=args.turnos)
    except AplicativoIndisponivel as erro:
        print(f"não deu para começar: {erro}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover — Ctrl+C do dono
        print("")
        return 0


def _com_as_opcoes_da_linha(configuracao: Configuracao, args: argparse.Namespace) -> Configuracao:
    """Opção de linha vale só para esta execução — ela **não** reescreve o arquivo do dono."""
    mudancas: dict[str, str] = {}
    if args.asr:
        mudancas["asr"] = str(args.asr)
    if args.tts:
        mudancas["tts"] = str(args.tts)
    if args.s2:
        mudancas["s2"] = str(args.s2)
    return configuracao.com(**mudancas) if mudancas else configuracao


def backend_escolhido_na_linha(ambiente: Mapping[str, str] | None = None) -> Backend:
    """Qual backend de áudio o ambiente pediu — mostrado no diagnóstico e nos erros."""
    from jarvis.audio_io.ambiente import backend_escolhido

    return backend_escolhido(ambiente)


__all__ = ["VARIAVEL_BACKEND", "Saida", "diagnosticar", "main"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
