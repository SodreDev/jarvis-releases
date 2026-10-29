"""O catálogo de modelos: ao vivo, guardada, do registro — e o que vem de fora passa pela forma."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from jarvis.provedores.catalogo import Catalogo, Origem, pasta_do_cache
from jarvis.provedores.interface import (
    Capacidades,
    ListagemIndisponivel,
    Modelo,
)
from jarvis.provedores.registro import RegraDeCapacidade
from jarvis.s2.motor import MotorDeConversa
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.registro import Motor

REGISTRO = Motor(
    id="conversa-falso",
    papel="conversa",
    onde=Onde.NUVEM,
    modelo="fixo-1",
    modelos=("fixo-2",),
    data_dos_modelos="2026-10-29",
    data_de_acesso="2026-10-29",
)
REGRAS = (
    RegraDeCapacidade(
        "conversa-falso", "vivo-*", Capacidades(visao=True, esforcos=("low",)), "teste", "2026"
    ),
)


@dataclass
class ProvedorFalso:
    modelos: tuple[Modelo, ...] = (Modelo("vivo-a", "Vivo A", Capacidades(contexto=1000)),)
    erro: str = ""
    chamadas: int = 0
    id: str = "conversa-falso"
    onde: Onde = Onde.NUVEM
    pedidos: list[str] = field(default_factory=list)

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        self.chamadas += 1
        if self.erro:
            raise ListagemIndisponivel(self.erro)
        return self.modelos

    def motor(  # pragma: no cover — não usado
        self, modelo: str, esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        raise AssertionError


class Relogio:
    def __init__(self) -> None:
        self.agora = 1_800_000_000.0

    def __call__(self) -> float:
        return self.agora


def test_lista_ao_vivo_e_guardada_e_completada_pelo_registro(tmp_path: Path) -> None:
    relogio = Relogio()
    catalogo = Catalogo(tmp_path, relogio=relogio)
    provedor = ProvedorFalso()

    listagem = catalogo.listar(provedor, REGISTRO, REGRAS)

    assert listagem.origem is Origem.PROVEDOR
    modelo = listagem.modelo("vivo-a")
    assert modelo is not None
    assert modelo.capacidades.contexto == 1000  # do provedor
    assert modelo.capacidades.visao is True  # do registro, que completa
    guardado = json.loads((tmp_path / "conversa-falso.json").read_text(encoding="utf-8"))
    assert guardado["modelos"][0]["id"] == "vivo-a"
    assert guardado["modelos"][0]["capacidades"]["visao"] is None  # guarda o que o provedor disse


def test_guardada_fresca_nao_abre_rede_e_forcar_abre(tmp_path: Path) -> None:
    relogio = Relogio()
    catalogo = Catalogo(tmp_path, relogio=relogio)
    provedor = ProvedorFalso()
    catalogo.listar(provedor, REGISTRO, REGRAS)
    relogio.agora += 3600

    assert catalogo.listar(provedor, REGISTRO, REGRAS).origem is Origem.CACHE
    assert provedor.chamadas == 1
    assert catalogo.listar(provedor, REGISTRO, REGRAS, forcar=True).origem is Origem.PROVEDOR
    assert provedor.chamadas == 2


def test_guardada_velha_tenta_a_de_agora_e_volta_a_ela_se_falhar(tmp_path: Path) -> None:
    relogio = Relogio()
    catalogo = Catalogo(tmp_path, relogio=relogio)
    provedor = ProvedorFalso()
    catalogo.listar(provedor, REGISTRO, REGRAS)
    relogio.agora += 2 * 24 * 3600
    provedor.erro = "sem rede"

    listagem = catalogo.listar(provedor, REGISTRO, REGRAS)

    assert provedor.chamadas == 2
    assert listagem.origem is Origem.CACHE
    assert "sem rede" in listagem.aviso and "guardada" in listagem.aviso


def test_sem_nada_guardado_vale_a_lista_do_registro(tmp_path: Path) -> None:
    provedor = ProvedorFalso(erro="falta a chave")

    listagem = Catalogo(tmp_path).listar(provedor, REGISTRO, REGRAS)

    assert listagem.origem is Origem.REGISTRO
    assert [m.id for m in listagem.modelos] == ["fixo-1", "fixo-2"]
    assert listagem.lida_em == "2026-10-29"
    assert "falta a chave" in listagem.aviso


def test_cache_mexido_ou_quebrado_vira_sem_cache(tmp_path: Path) -> None:
    arquivo = tmp_path / "conversa-falso.json"
    catalogo = Catalogo(tmp_path)
    for conteudo in ("{não é json", json.dumps({"versao": 99}), json.dumps([1, 2])):
        arquivo.write_text(conteudo, encoding="utf-8")
        assert catalogo.guardada(REGISTRO) is None
    assert catalogo.sem_rede(REGISTRO).origem is Origem.REGISTRO


def test_o_que_vem_de_fora_passa_pela_forma(tmp_path: Path) -> None:
    """Id com espaço, aspas ou controle fica de fora; nome perde controle e quebra de linha."""
    arquivo = tmp_path / "conversa-falso.json"
    arquivo.write_text(
        json.dumps(
            {
                "versao": 1,
                "lida_em": "2026-10-29T10:00:00Z",
                "modelos": [
                    {"id": "bom/modelo-1:free", "nome": "Bom\n<b>nome</b>\u0007"},
                    {"id": "ruim modelo"},
                    {"id": "--model=x"},
                    {"id": 'aspas"'},
                    {"id": "bom/modelo-1:free", "nome": "repetido"},
                    {"id": "outro", "capacidades": {"visao": "sim", "contexto": -5}},
                ],
            }
        ),
        encoding="utf-8",
    )

    listagem = Catalogo(tmp_path).guardada(REGISTRO)

    assert listagem is not None
    assert [m.id for m in listagem.modelos] == ["bom/modelo-1:free", "outro"]
    assert listagem.modelos[0].nome == "Bom <b>nome</b>"
    assert listagem.modelos[1].capacidades == Capacidades()


def test_modelo_fora_da_forma_nao_existe() -> None:
    for ruim in ("", " x", "a b", "-flag", "x;rm", "a" * 200):
        with pytest.raises(ValueError):
            Modelo(ruim)


def test_pasta_do_cache_nao_cai_na_casa_do_dono_num_ambiente_explicito(tmp_path: Path) -> None:
    assert pasta_do_cache({}) is None
    assert pasta_do_cache({"XDG_CACHE_HOME": str(tmp_path)}) == tmp_path / "jarvis" / "modelos"
    assert pasta_do_cache({"HOME": str(tmp_path)}) == tmp_path / ".cache" / "jarvis" / "modelos"


def test_sem_pasta_de_cache_lista_sem_gravar() -> None:
    provedor = ProvedorFalso()
    catalogo = Catalogo(None)

    assert catalogo.listar(provedor, REGISTRO).origem is Origem.PROVEDOR
    assert catalogo.listar(provedor, REGISTRO).origem is Origem.PROVEDOR
    assert provedor.chamadas == 2
