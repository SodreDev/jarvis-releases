"""A conversa sobrevive ao reinício (dono, 2026-10-18; ADR-0026).

Fechar e reabrir mantém: os últimos turnos voltam à tela **e** ao contexto do cérebro, só o que
o dono ouviu do Jarvis; "nova conversa" limpa os dois e vale no disco; sem chaveiro, degrada.
"""

from __future__ import annotations

from pathlib import Path

from jarvis.memoryd.cofre import CofreFernet, CofreIndisponivel, nova_chave
from jarvis.memoryd.conversa import ConversaPersistente, abrir_conversa
from jarvis.memoryd.indice import IndiceEmMemoria
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao

CHAVE = nova_chave()


def _abrir(raiz: Path) -> ConversaPersistente:
    return abrir_conversa(raiz, cofre=lambda: CofreFernet(CHAVE), indice=IndiceEmMemoria())


def _falar(
    conversa: ConversaPersistente, dono: str, jarvis: str, *, tocado: str | None = None
) -> None:
    """Um turno inteiro pelo livro, como o cérebro o grava."""
    assert conversa.livro is not None
    conversa.livro.gravar_turno(
        session_id=conversa.conversa_id, papel="dono", texto=dono, trust="user_voice"
    )
    conversa.livro.gravar_turno(
        session_id=conversa.conversa_id,
        papel="jarvis",
        texto=jarvis if tocado is None else tocado,
        trust="system",
        played_ms=900,
        interrompida=tocado is not None,
    )


def test_fechar_e_reabrir_mantem_a_conversa(tmp_path: Path) -> None:
    primeira = _abrir(tmp_path)
    assert primeira.ativa
    _falar(primeira, "que dia vem depois de quinta?", "Sexta-feira.")
    _falar(primeira, "e depois?", "Sábado, e depois domingo.", tocado="Sábado, e")
    identificador = primeira.conversa_id
    primeira.fechar()

    segunda = _abrir(tmp_path)

    assert segunda.conversa_id == identificador
    voltou = segunda.recentes()
    assert [(t.papel, t.texto, t.interrompida) for t in voltou] == [
        ("dono", "que dia vem depois de quinta?", False),
        ("jarvis", "Sexta-feira.", False),
        ("dono", "e depois?", False),
        ("jarvis", "Sábado, e", True),
    ], "do Jarvis volta só o que tocou, e a interrupção vem marcada"


def test_o_bruto_da_conversa_fica_cifrado_em_disco(tmp_path: Path) -> None:
    """ADR-0026, regra 6: o bruto vai cifrado. O texto *redigido* (índice léxico) não é cifrado
    ainda — é a pergunta aberta 1 da ADR, e a tela de privacidade diz isso."""
    conversa = _abrir(tmp_path)
    _falar(conversa, "meu apelido secreto é carambola", "Guardei.")
    assert conversa.livro is not None
    blobs = [
        bytes(r["cifrado"]) for r in conversa.livro.con.execute("SELECT cifrado FROM raw_blob")
    ]

    assert blobs, "o bruto foi gravado"
    assert all(b"carambola" not in blob for blob in blobs)
    assert conversa.livro.texto_bruto(
        str(conversa.livro.con.execute("SELECT id FROM episode LIMIT 1").fetchone()[0])
    ), "e decifra com a chave do cofre"


def test_so_voltam_os_ultimos_turnos_em_ordem(tmp_path: Path) -> None:
    conversa = _abrir(tmp_path)
    for i in range(10):
        _falar(conversa, f"pergunta {i}", f"resposta {i}")

    ultimos = conversa.recentes(4)

    assert [t.texto for t in ultimos] == ["pergunta 8", "resposta 8", "pergunta 9", "resposta 9"]


def test_nova_conversa_limpa_e_vale_no_disco(tmp_path: Path) -> None:
    conversa = _abrir(tmp_path)
    _falar(conversa, "assunto antigo", "Certo.")
    antiga = conversa.conversa_id

    nova = conversa.nova()

    assert nova != antiga
    assert conversa.recentes() == []
    conversa.fechar()
    reaberta = _abrir(tmp_path)
    assert reaberta.conversa_id == nova, "fechar logo depois da 'nova conversa' não traz a antiga"
    assert reaberta.recentes() == []
    assert "antigo" in str(reaberta.livro.buscar_historico("antigo")), (  # type: ignore[union-attr]
        "a conversa antiga continua no histórico: só deixa de voltar sozinha"
    )


def test_sem_chaveiro_degrada_com_a_frase_e_sem_historico(tmp_path: Path) -> None:
    def sem_cofre() -> CofreFernet:
        raise CofreIndisponivel("chaveiro do SO indisponível: NoKeyringError")

    conversa = abrir_conversa(tmp_path, cofre=sem_cofre)

    assert not conversa.ativa
    assert "sem histórico em disco" in conversa.aviso
    assert conversa.recentes() == []
    assert not list(tmp_path.rglob("*.sqlite")), "sem cofre, nada da conversa vai para o disco"


def test_banco_ilegivel_nao_derruba_a_abertura(tmp_path: Path) -> None:
    pasta = tmp_path / "memoria"
    pasta.mkdir()
    (pasta / "livro.sqlite").write_bytes(b"isto nao e um banco sqlite " * 40)

    conversa = _abrir(tmp_path)

    assert conversa.recentes() == []  # degradou, não caiu


def test_o_laco_reabre_com_a_conversa_no_contexto_e_continua_a_gravar(tmp_path: Path) -> None:
    configuracao = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco")
    ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo"}

    def laco(conversa: ConversaPersistente, motor: MotorRoteirizado) -> Aplicativo:
        aplicativo = Aplicativo(
            configuracao=configuracao,
            raiz=tmp_path,
            ambiente=ambiente,
            caminho_de_saida=tmp_path / "saida.wav",
            conversa=conversa,
        )
        aplicativo._motor = motor
        aplicativo.abrir(com_asr=False)
        return aplicativo

    primeiro = laco(_abrir(tmp_path), MotorRoteirizado(resposta="Sexta-feira."))
    primeiro.rodar_texto(["que dia vem depois de quinta?"])
    assert primeiro.conversa is not None
    primeiro.conversa.fechar()

    motor = MotorRoteirizado(resposta="Sábado.")
    segundo = laco(_abrir(tmp_path), motor)
    segundo.rodar_texto(["e depois?"])

    contexto = motor.pedidos[-1]
    assert [(m.papel, m.texto) for m in contexto.mensagens][:2] == [
        ("dono", "que dia vem depois de quinta?"),
        ("jarvis", "Sexta-feira."),
    ], "o cérebro recomeçou sabendo o que foi dito antes do reinício"
    assert contexto.mensagens[-1].texto == "e depois?"
    assert segundo.conversa is not None
    assert [t.texto for t in segundo.conversa.recentes()][-2:] == ["e depois?", "Sábado."]


def test_nova_conversa_no_laco_esquece_o_contexto_no_turno_seguinte(tmp_path: Path) -> None:
    configuracao = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco")
    conversa = _abrir(tmp_path)
    aplicativo = Aplicativo(
        configuracao=configuracao,
        raiz=tmp_path,
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_saida=tmp_path / "saida.wav",
        conversa=conversa,
    )
    motor = MotorRoteirizado(resposta="Certo.")
    aplicativo._motor = motor
    aplicativo.abrir(com_asr=False)
    aplicativo.rodar_texto(["primeiro assunto"])

    conversa.nova()
    aplicativo.rodar_texto(["segundo assunto"])

    assert [m.texto for m in motor.pedidos[-1].mensagens] == ["segundo assunto"]
