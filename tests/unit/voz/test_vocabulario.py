"""O vocabulário do dono (ADR-0044): o arquivo fora do repositório, a pós-correção e a pronúncia.

Tudo em pasta temporária do teste (nunca a `~/.config/jarvis/` do dono) e com nomes fictícios.
"""

from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import pytest

from jarvis.voz.vocabulario import (
    ARQUIVO_APRENDIDO,
    ARQUIVO_DO_DONO,
    RepositorioDoVocabulario,
    Termo,
    Vocabulario,
    VocabularioInvalido,
    ler_vocabulario,
    pasta_do_vocabulario,
)

RAIZ = Path(__file__).resolve().parents[3]
EXEMPLO = RAIZ / "docs" / "exemplos" / "vocabulario.toml"


def _vocabulario(*termos: Termo) -> Vocabulario:
    return Vocabulario(termos=termos)


# --- onde mora e como lê -------------------------------------------------------------------------
def test_mora_ao_lado_da_configuracao_e_nao_no_repositorio(tmp_path: Path) -> None:
    pasta = pasta_do_vocabulario({"XDG_CONFIG_HOME": str(tmp_path)})
    assert pasta == tmp_path / "jarvis"
    assert RAIZ not in pasta.parents
    assert pasta_do_vocabulario({"HOME": str(tmp_path)}) == tmp_path / ".config" / "jarvis"


def test_ambiente_explicito_sem_casa_nao_tem_vocabulario() -> None:
    """O ambiente da suíte não leva à pasta do dono: sem casa declarada, sem vocabulário."""
    assert pasta_do_vocabulario({"CI": "1"}) is None
    assert RepositorioDoVocabulario.padrao({}) is None


def test_o_exemplo_do_repositorio_e_lido_inteiro(tmp_path: Path) -> None:
    (tmp_path / ARQUIVO_DO_DONO).write_text(EXEMPLO.read_text(encoding="utf-8"), encoding="utf-8")

    vocabulario = ler_vocabulario(tmp_path)

    assert vocabulario.avisos == ()
    assert [t.escrita for t in vocabulario.termos] == [
        "Steam",
        "Spotify",
        "Kdenlive",
        "Kauã Ximenes",
    ]
    assert vocabulario.ignorar == ("fala galera",)


def test_sem_arquivo_e_vazio_e_sem_aviso(tmp_path: Path) -> None:
    vocabulario = ler_vocabulario(tmp_path / "nao-existe")
    assert vocabulario == Vocabulario()


def test_arquivo_quebrado_nao_derruba_a_voz(tmp_path: Path) -> None:
    (tmp_path / ARQUIVO_DO_DONO).write_text("[[termo]\nescrita = ", encoding="utf-8")

    vocabulario = ler_vocabulario(tmp_path)

    assert vocabulario.termos == ()
    assert vocabulario.avisos and "não deu para ler" in vocabulario.avisos[0]


def test_entrada_torta_fica_de_fora_pela_posicao_sem_o_texto(tmp_path: Path) -> None:
    (tmp_path / ARQUIVO_DO_DONO).write_text(
        '[[termo]]\nescrita = "Ana Ribeiro"\n\n'
        '[[termo]]\nescrita = "<script>"\n\n'
        '[[termo]]\nescrita = "Bia"\ntipo = "planeta"\n',
        encoding="utf-8",
    )

    vocabulario = ler_vocabulario(tmp_path)

    assert [t.escrita for t in vocabulario.termos] == ["Ana Ribeiro"]
    assert vocabulario.avisos == (
        f"{ARQUIVO_DO_DONO}: o 2º [[termo]] não serve e ficou de fora",
        f"{ARQUIVO_DO_DONO}: o 3º [[termo]] não serve e ficou de fora",
    )


# --- ouvir: a pós-correção -----------------------------------------------------------------------
def test_o_apelido_vira_a_escrita_sem_caixa_e_sem_acento() -> None:
    vocabulario = _vocabulario(Termo("Steam", ouvido=("stim", "estim")))
    assert vocabulario.corrigir("abre o Stim, por favor") == "abre o Steam, por favor"
    assert vocabulario.corrigir("ESTÍM") == "Steam"


def test_o_apelido_so_casa_palavra_inteira() -> None:
    vocabulario = _vocabulario(Termo("Steam", ouvido=("stim",)))
    assert vocabulario.corrigir("estimativa do stimulus") == "estimativa do stimulus"


def test_apelido_de_varias_palavras_casa_com_espaco_ou_hifen() -> None:
    vocabulario = _vocabulario(Termo("Kdenlive", ouvido=("que dei live",)))
    assert vocabulario.corrigir("abre o que dei live agora") == "abre o Kdenlive agora"
    assert vocabulario.corrigir("abre o que-dei-live") == "abre o Kdenlive"
    assert vocabulario.corrigir("que, dei, live") == "que, dei, live", "vírgula separa"


def test_o_nome_composto_escrito_de_outro_jeito_e_achado_pela_fonetica() -> None:
    vocabulario = _vocabulario(Termo("Thiago Nigro", tipo="pessoa"))
    assert vocabulario.corrigir("manda mensagem para o Tiago Negro") == (
        "manda mensagem para o Thiago Nigro"
    )
    assert vocabulario.corrigir("Tiago Negro e Tiago Negro") == "Thiago Nigro e Thiago Nigro"


def test_a_fonetica_nao_troca_palavra_solta_nem_nome_parecido_demais_de_longe() -> None:
    """Palavra solta casaria com palavra comum ("discórdia" não é o Discord)."""
    vocabulario = _vocabulario(Termo("Discord"), Termo("Thiago Nigro"))
    assert vocabulario.corrigir("a discórdia entre eles") == "a discórdia entre eles"
    assert vocabulario.corrigir("o Tiago e o negro") == "o Tiago e o negro"
    assert vocabulario.corrigir("Diego Negrão") == "Diego Negrão"


def test_sem_vocabulario_o_texto_volta_igual() -> None:
    assert Vocabulario().corrigir("abre o disco") == "abre o disco"


# --- falar: a pronúncia --------------------------------------------------------------------------
def test_a_pronuncia_troca_so_para_o_tts_e_respeita_o_motor() -> None:
    vocabulario = _vocabulario(
        Termo("Steam", fala="Stím"),
        Termo("Spotify", fala="Spótifai", motores=("tts-piper-epitran",)),
    )
    assert vocabulario.pronunciar("Abri o Steam e o Spotify.", "tts-piper-epitran") == (
        "Abri o Stím e o Spótifai."
    )
    assert vocabulario.pronunciar("Abri o Steam e o Spotify.", "tts-elevenlabs") == (
        "Abri o Stím e o Spotify."
    )


def test_o_nome_composto_e_pronunciado_antes_do_simples() -> None:
    vocabulario = _vocabulario(
        Termo("Code", fala="Côudi"), Termo("Visual Studio Code", fala="Víjual Estúdio Côudi")
    )
    assert vocabulario.pronunciar("Abri o Visual Studio Code.") == "Abri o Víjual Estúdio Côudi."


def test_a_pronuncia_mais_recente_vale() -> None:
    vocabulario = _vocabulario(Termo("Steam", fala="Estim"), Termo("Steam", fala="Stím"))
    assert vocabulario.pronunciar("o Steam") == "o Stím"


# --- a dica --------------------------------------------------------------------------------------
def test_a_dica_poe_o_aprendido_mais_recente_primeiro_e_o_do_dono_na_ordem() -> None:
    vocabulario = _vocabulario(
        Termo("Ana Ribeiro"),
        Termo("Kdenlive"),
        Termo("Steam", fala="Stím", id="v-00000001"),
        Termo("Lutris", ouvido=("lutres",), id="v-00000002"),
        Termo("steam"),
    )
    assert vocabulario.termos_da_dica() == ["Lutris", "Steam", "Ana Ribeiro", "Kdenlive"]


# --- o que o Jarvis aprende ----------------------------------------------------------------------
def test_aprender_grava_no_arquivo_do_jarvis_e_nunca_no_do_dono(tmp_path: Path) -> None:
    do_dono = tmp_path / ARQUIVO_DO_DONO
    do_dono.write_text('# meus nomes\n[[termo]]\nescrita = "Ana Ribeiro"\n', encoding="utf-8")
    antes = do_dono.read_bytes()
    repositorio = RepositorioDoVocabulario(tmp_path)

    termo = repositorio.aprender("Discord", ouvido=["discorde"], tipo="app")

    assert do_dono.read_bytes() == antes, "o arquivo do dono foi mexido"
    aprendido = tmp_path / ARQUIVO_APRENDIDO
    dados = tomllib.loads(aprendido.read_text(encoding="utf-8"))
    assert dados["termo"] == [
        {"id": termo.id, "escrita": "Discord", "ouvido": ["discorde"], "tipo": "app"}
    ]
    assert stat.S_IMODE(aprendido.stat().st_mode) == 0o600
    vocabulario = repositorio.carregar()
    assert [t.escrita for t in vocabulario.termos] == ["Ana Ribeiro", "Discord"]
    assert vocabulario.corrigir("abre o discorde") == "abre o Discord"


def test_esquecer_tira_so_aquela_correcao(tmp_path: Path) -> None:
    repositorio = RepositorioDoVocabulario(tmp_path)
    primeira = repositorio.aprender("Steam", fala="Stím")
    segunda = repositorio.aprender("Lutris", ouvido=["lutres"])

    assert repositorio.esquecer(primeira.id) == primeira
    assert [t.escrita for t in repositorio.carregar().termos] == ["Lutris"]
    assert repositorio.esquecer(primeira.id) is None
    assert repositorio.esquecer(segunda.id) == segunda
    assert repositorio.carregar().termos == ()


@pytest.mark.parametrize(
    ("argumentos", "trecho"),
    [
        ({"escrita": "Discord"}, "ouvido"),
        ({"escrita": "", "fala": "Díscord"}, "escrita"),
        ({"escrita": 'Disc"ord', "fala": "Díscord"}, "escrita"),
        ({"escrita": "Discord", "ouvido": ["o"]}, "comum"),
        ({"escrita": "Discord", "ouvido": ["x" * 81]}, "ouvido"),
        ({"escrita": "Discord", "fala": "Díscord", "tipo": "planeta"}, "tipo"),
        ({"escrita": "Discord", "fala": "[[termo]]"}, "fala"),
    ],
)
def test_correcao_que_nao_serve_e_recusada_dizendo_por_que(
    tmp_path: Path, argumentos: dict[str, object], trecho: str
) -> None:
    repositorio = RepositorioDoVocabulario(tmp_path)
    escrita = str(argumentos.pop("escrita"))
    with pytest.raises(VocabularioInvalido, match=trecho):
        repositorio.aprender(escrita, **argumentos)  # type: ignore[arg-type]
    assert not (tmp_path / ARQUIVO_APRENDIDO).exists()


def test_o_apelido_igual_a_escrita_nao_conta(tmp_path: Path) -> None:
    repositorio = RepositorioDoVocabulario(tmp_path)
    with pytest.raises(VocabularioInvalido, match="ouvido"):
        repositorio.aprender("Discord", ouvido=["discord", "DISCORD"])
