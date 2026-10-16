"""Portão de motor de voz: registro, licença, termos e o interruptor da nuvem (ADR-0017).

É o mesmo desenho do carregador de voz do F1-09 (`jarvis.agentd.tts.carregar_voz`), um nível
acima: ali a pergunta é "esta voz pode entrar no produto?"; aqui é "este **motor** pode rodar,
e o áudio do dono pode sair da máquina?". As duas respostas vêm de **arquivo de dados**
(`licenses/motores.toml`), não de prosa e não de quem chama.

Quatro recusas, na ordem em que acontecem:

1. **motor não registrado** — licença que ninguém verificou não é permissiva por otimismo
   (ADR-0012);
2. **licença do cliente não permissiva** — a mesma régua da ADR-0011, aplicada à biblioteca
   que faz a chamada, não ao peso do modelo;
3. **campo obrigatório vazio num motor de nuvem** — "no v0, 'não verificado' não liga nuvem"
   (ADR-0017, política 4). É esta regra que mantém o `tts-edge` fora: o endpoint de
   *read-aloud* do Edge não tem página de termos para ler;
4. **nuvem não ligada pelo dono** — o registro nasce com todo motor de nuvem desligado, e
   ligar é escolha que vem da configuração do dono, nunca de frase, de capacidade ou de
   argumento de quem chama (P12, §5.5).

E uma obrigação: `frase_de_aviso` monta, **dos campos**, o que a UI tem de mostrar ao ligar
nuvem. Não é texto escrito à mão em cada tela — é derivado do registro, então mudar o fato
muda o aviso, e esquecer o fato barra o motor.
"""

from __future__ import annotations

import tomllib
from collections.abc import Collection, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Final

from jarvis.dados import caminho
from jarvis.licencas import Categoria, classificar
from jarvis.voz.interface import Onde

ARQUIVO_MOTORES: Final = caminho("licenses/motores.toml")

CAMPOS_DE_NUVEM: Final[tuple[str, ...]] = (
    "uso_comercial",
    "retencao_declarada",
    "treina_com_entrada",
    "dono_da_saida",
)
"""Os quatro campos da ADR-0017 (política 3 e 4). Vazio barra, e é de propósito."""

CAMPOS_DE_PROCEDENCIA: Final[tuple[str, ...]] = ("fonte", "data_de_acesso")
"""Vale para **todo** motor: fato sem fonte e sem data não é fato (ADR-0012)."""

CAMPOS_DOS_MODELOS: Final[tuple[str, ...]] = ("fonte_dos_modelos", "data_dos_modelos")
"""Motor com lista de modelos tem de dizer onde a lista foi lida e quando — a lista muda
mais depressa que o contrato (modelo novo, modelo aposentado)."""


def _ou_desconhecido(valor: str) -> str:
    """Campo vazio vira "não verificado" na frase, nunca um espaço em branco.

    Espaço em branco num aviso lê-se como "tudo bem aqui"; "não verificado" lê-se como o que
    é. A diferença importa porque é esta frase que o dono vê antes de ligar nuvem.
    """
    return valor.strip() or "**não verificado**"


class MotorRecusado(RuntimeError):
    """O motor não roda: não está registrado, a licença não presta, falta termo ou é nuvem
    desligada. A mensagem diz **qual** das quatro, porque o dono precisa saber o que fazer."""


@dataclass(frozen=True, slots=True)
class Motor:
    """Um motor de voz como o registro o descreve. Dado, não objeto executável."""

    id: str
    papel: str
    onde: Onde
    ligado: bool = False
    implementacao: str = ""
    modelo: str = ""
    voz: str = ""
    servico: str = ""
    endereco: str = ""
    variavel_da_chave: str = ""
    licenca_do_cliente: str = ""
    cliente: str = ""
    estado: str = "em_uso"
    marca_dagua: str = ""
    preco: str = ""
    uso_comercial: str = ""
    retencao_declarada: str = ""
    treina_com_entrada: str = ""
    dono_da_saida: str = ""
    fonte: str = ""
    fonte_tecnica: str = ""
    fonte_retencao: str = ""
    data_de_acesso: str = ""
    nota: str = ""
    modelos: tuple[str, ...] = ()
    """Os modelos que o dono pode escolher **dentro** deste motor, além de `modelo` (o
    padrão). Vazio = o motor tem um modelo só. Cada um foi conferido na página oficial do
    serviço (`fonte_dos_modelos`, `data_dos_modelos`): modelo que não está aqui não roda."""
    fonte_dos_modelos: str = ""
    data_dos_modelos: str = ""

    @property
    def categoria_da_licenca(self) -> Categoria:
        return classificar(self.licenca_do_cliente)

    @property
    def na_nuvem(self) -> bool:
        return self.onde is Onde.NUVEM

    @property
    def campos_vazios(self) -> tuple[str, ...]:
        """Campos obrigatórios que ninguém preencheu. Para nuvem, qualquer um deles barra."""
        obrigatorios = CAMPOS_DE_PROCEDENCIA + (CAMPOS_DE_NUVEM if self.na_nuvem else ())
        if self.modelos:
            obrigatorios += CAMPOS_DOS_MODELOS
        return tuple(campo for campo in obrigatorios if not str(getattr(self, campo)).strip())

    @property
    def modelos_permitidos(self) -> tuple[str, ...]:
        """O padrão primeiro, depois os outros do registro, sem repetir."""
        return tuple(dict.fromkeys((self.modelo, *self.modelos)))

    @property
    def marca_o_audio(self) -> bool:
        """O motor marca o áudio que o assistente fala? (ADR-0017, política 5.)

        "não declarada" **não** é "não": é falta de informação, e a frase do aviso diz isso
        com as palavras do registro em vez de traduzir para um booleano otimista.
        """
        return str(self.marca_dagua).strip().lower() not in {"", "não", "nao", "no", "false"}

    @property
    def o_que_sai(self) -> str:
        return "o seu áudio" if self.papel == "asr" else "o texto que o Jarvis vai falar"

    @property
    def frase_de_aviso(self) -> str:
        """O aviso obrigatório de nuvem, montado **dos campos** (ADR-0017, política 3).

        Motor local não tem aviso: nada sai da máquina, e inventar uma frase aqui ensinaria o
        dono a ignorar as que importam.
        """
        if not self.na_nuvem:
            return ""
        partes: list[str] = []
        if set(self.campos_vazios) & set(CAMPOS_DE_NUVEM):
            partes.append(
                "ATENÇÃO: este serviço não publica termos para este uso, então não há "
                "contrato lido — o que vem abaixo é o que se sabe, e o resto é desconhecido."
            )
        partes += [
            f"Com {self.id} ligado, {self.o_que_sai} sai desta máquina para {self.servico}.",
            f"Retenção declarada: {_ou_desconhecido(self.retencao_declarada)}.",
            f"Treina com a entrada: {_ou_desconhecido(self.treina_com_entrada)}.",
            f"Dono da saída: {_ou_desconhecido(self.dono_da_saida)}.",
            f"Uso comercial: {_ou_desconhecido(self.uso_comercial)}.",
        ]
        if self.marca_o_audio:
            partes.append(f"Marca d'água no áudio: {self.marca_dagua}.")
        partes.append(f"Fonte: {self.fonte} (lida em {self.data_de_acesso}).")
        return " ".join(partes)


def _motor_de_dict(bruto: dict[str, Any]) -> Motor:
    """Campo do TOML que o `Motor` não conhece é **ignorado**, não é erro.

    O registro é lido por gente e vai ganhar campo novo (preço, latência medida) antes de o
    código precisar dele. Quebrar a leitura por causa de um campo a mais faria o portão de
    licença falhar por documentação — e quem barra motor tem de barrar por licença, não por
    chave desconhecida. O que **não** é opcional são os campos obrigatórios: eles faltando,
    `campos_vazios` barra.
    """
    conhecidos = {c.name for c in fields(Motor)}
    dados: dict[str, Any] = {chave: valor for chave, valor in bruto.items() if chave in conhecidos}
    dados["onde"] = Onde(str(bruto.get("onde", Onde.LOCAL)))
    dados["ligado"] = bool(bruto.get("ligado", False))
    dados["modelos"] = tuple(str(m) for m in bruto.get("modelos", ()))
    return Motor(**dados)


def ler_motores(arquivo: Path = ARQUIVO_MOTORES) -> tuple[Motor, ...]:
    """Todos os motores do registro, na ordem do arquivo."""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    return tuple(_motor_de_dict(bruto) for bruto in dados.get("motor", []))


def motor_registrado(identificador: str, *, arquivo: Path = ARQUIVO_MOTORES) -> Motor | None:
    return next((m for m in ler_motores(arquivo) if m.id == identificador), None)


def motores_de(
    papel: str = "",
    *,
    onde: Onde | None = None,
    arquivo: Path = ARQUIVO_MOTORES,
) -> tuple[Motor, ...]:
    """Filtro para o diagnóstico e para a UI listarem o que existe."""
    return tuple(
        m
        for m in ler_motores(arquivo)
        if (not papel or m.papel == papel) and (onde is None or m.onde is onde)
    )


def exigir_motor(
    identificador: str,
    *,
    arquivo: Path = ARQUIVO_MOTORES,
    nuvem_ligada: Collection[str] = (),
    permitir_fora_do_produto: bool = False,
    sem_termos_aceitos: Collection[str] = (),
) -> Motor:
    """Devolve o motor, ou recusa dizendo qual das quatro regras barrou.

    `nuvem_ligada` é a lista de motores de nuvem que **o dono** ligou na configuração dele. Ela
    entra por parâmetro, e não é lida aqui de variável de ambiente, para a origem do
    interruptor ser visível em quem chama: quem liga nuvem é a configuração do dono, lida pelo
    aplicativo, nunca uma variável que qualquer processo pode exportar.

    `permitir_fora_do_produto` libera **só** motor cujo registro diz `estado =
    "fora_do_produto"` — hoje, o piper com espeak-ng, que é linha de base de medição e não
    caminho de produto. É a mesma assimetria do registro de ferramentas externas (a porta de
    licença avisa em vez de bloquear quando a GPL roda fora do produto), e quem passa o
    parâmetro é `tools/`, onde isso é permitido. `src/` nunca passa, e há teste para isso.
    """
    motor = motor_registrado(identificador, arquivo=arquivo)
    if motor is None:
        raise MotorRecusado(
            f"motor {identificador!r} não está em {arquivo.name}: motor que ninguém verificou "
            "não roda (ADR-0012, ADR-0017)"
        )
    categoria = motor.categoria_da_licenca
    fora_do_produto = motor.estado == "fora_do_produto" and permitir_fora_do_produto
    if categoria is not Categoria.PERMISSIVA and not fora_do_produto:
        raise MotorRecusado(
            f"motor {identificador!r} usa cliente {motor.cliente!r} com licença "
            f"{motor.licenca_do_cliente!r} ({categoria}), que não é permissiva (ADR-0011)"
        )
    vazios = motor.campos_vazios
    if vazios:
        quais = ", ".join(vazios)
        # Procedência (fonte e data) **nunca** é dispensável: sem ela nem dá para saber o que
        # se está aceitando. Já os quatro campos de termo podem faltar porque o serviço não
        # publica contrato — e aí a escolha de usar assim mesmo é do dono, motor por motor,
        # escrita na configuração dele (`nuvem_sem_termos`). O aviso passa a abrir dizendo
        # que não há termos verificados, e continua dizendo isso toda vez.
        sem_procedencia = set(vazios) & set(CAMPOS_DE_PROCEDENCIA)
        if sem_procedencia or identificador not in sem_termos_aceitos:
            raise MotorRecusado(
                f"motor {identificador!r} está com campo obrigatório vazio no registro: "
                f"{quais}. No v0, 'não verificado' não liga nuvem (ADR-0017, política 4)"
            )
    if motor.na_nuvem and not (motor.ligado or identificador in nuvem_ligada):
        raise MotorRecusado(
            f"motor {identificador!r} é de nuvem e está desligado: {motor.o_que_sai} sairia "
            f"desta máquina para {motor.servico}. Ligar é escolha do dono, na configuração "
            "(ADR-0017, política 1 e 2; SPEC §5.5/P12)"
        )
    return motor


def exigir_modelo(motor: Motor, modelo: str) -> str:
    """O modelo que vai na chamada: o pedido, se o registro o lista; o padrão, se vazio.

    Modelo fora da lista **recusa**, como motor fora do registro: o nome do modelo vai para o
    serviço de outra empresa, e um nome que ninguém conferiu na página dela pode ser um
    modelo aposentado, de outra API ou de outro idioma.
    """
    if not modelo:
        return motor.modelo
    if modelo not in motor.modelos_permitidos:
        raise MotorRecusado(
            f"o modelo {modelo!r} não está registrado para {motor.id!r}. Registrados: "
            f"{', '.join(motor.modelos_permitidos)} (conferidos em {motor.data_dos_modelos or '?'})"
        )
    return modelo


@dataclass(frozen=True, slots=True)
class Falta:
    """O que falta para um motor rodar — para o `--diagnostico` dizer em vez de adivinhar."""

    motor: str
    motivo: str


def conferir(
    *,
    arquivo: Path = ARQUIVO_MOTORES,
    nuvem_ligada: Collection[str] = (),
    ambiente: Collection[str] = (),
) -> tuple[Falta, ...]:
    """Varredura do registro: o que está pronto e o que falta, sem carregar nada.

    `ambiente` são os **nomes** das variáveis presentes no ambiente — nomes, nunca valores.
    É o que deixa o diagnóstico dizer "falta a chave" sem ler, imprimir ou guardar a chave.
    """
    faltas: list[Falta] = []
    for motor in ler_motores(arquivo):
        try:
            exigir_motor(motor.id, arquivo=arquivo, nuvem_ligada=nuvem_ligada)
        except MotorRecusado as erro:
            faltas.append(Falta(motor=motor.id, motivo=str(erro)))
            continue
        if motor.variavel_da_chave and motor.variavel_da_chave not in ambiente:
            faltas.append(
                Falta(
                    motor=motor.id,
                    motivo=f"a variável {motor.variavel_da_chave} não está no ambiente",
                )
            )
    return tuple(faltas)


MOTORES_DE_NUVEM_LIGADOS_POR_PADRAO: Final[Sequence[str]] = ()
"""Documenta a política 1 da ADR-0017 em código: a lista é vazia, e um teste cobra isso do
registro — "local por padrão" não pode depender de ninguém reler o TOML."""
