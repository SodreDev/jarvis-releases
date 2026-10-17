"""Corpus C2 **sintético e anotado** em pt-BR para as medições §8.1 e §8.2 (fatia 7).

A SPEC pede o C2 anotado pelo dono e pelo arquiteto, sobre a vida dele. Este é o substituto
declarado: gerado com semente, com gabarito por construção. Ele **não** diz quanto o Jarvis
acerta na vida do dono; diz se uma peça é melhor que outra **no mesmo** corpus, que é o que as
regras de decisão da §8.1/§8.2 comparam. Toda decisão tirada dele é provisória até o C2 real.

O que ele cobre, pelos subconjuntos da §8.2:

- **C2a factual de 1 salto** — preferências do dono e fatos de pessoas, com a pergunta
  parafraseada; pergunta pelo **apelido** quando o fato usa o nome (diminutivo); termos em inglês
  na pergunta e português no fato (code-switch); siglas.
- **C2b relacional/multi-salto** — "o arquivo que minha irmã mandou sobre a proposta da Sol":
  a resposta está em duas memórias ligadas por uma entidade que a pergunta não nomeia.
- **C2c contradição temporal** — a preferência mudou (`atualizar`); o gabarito é a vigente e a
  antiga é **vencida**, que não pode voltar como atual (gate 4).
- **C2d negativos** — sem resposta no corpus, inclusive os difíceis: a pessoa existe, o fato
  perguntado não ("quando é o aniversário do Nando?" quando só se sabe onde ele trabalha).

Ficam **fora** (e o relatório diz): datas relativas resolvidas ("terça passada" → data), que
pedem o passo 4 da §6.8 com interpretação de tempo; e precisão de aresta, porque aqui a aresta
vem do gabarito do gerador, não de um extrator.

Distratores: centenas de memórias do mesmo formato das do gabarito (outras pessoas mandando
outros arquivos de outros clientes) e conversa à toa como turno, que o filtro tem de deixar fora.
"""

from __future__ import annotations

import hashlib
import json
import random
import unicodedata
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Literal

SEMENTE: Final = 20261016
Subconjunto = Literal["C2a", "C2b", "C2c", "C2d"]


@dataclass(frozen=True, slots=True)
class Entidade:
    nome: str
    tipo: str
    apelidos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Fato:
    """Uma fala do dono que vira memória ativa (`lembrar`), ou que substitui outra."""

    chave: str
    texto: str
    substitui: str | None = None


@dataclass(frozen=True, slots=True)
class Aresta:
    origem: str
    relacao: str
    destino: str
    fato: str
    """A chave do fato cuja fala sustenta a aresta (proveniência, §6.7)."""


@dataclass(frozen=True, slots=True)
class Consulta:
    id: str
    subconjunto: Subconjunto
    texto: str
    gabarito: tuple[str, ...]
    vencidos: tuple[str, ...] = ()


@dataclass(slots=True)
class Corpus:
    entidades: list[Entidade] = field(default_factory=list)
    fatos: list[Fato] = field(default_factory=list)
    arestas: list[Aresta] = field(default_factory=list)
    conversa: list[str] = field(default_factory=list)
    consultas: list[Consulta] = field(default_factory=list)

    @property
    def hash(self) -> str:
        bruto = json.dumps(
            {k: [asdict(x) if not isinstance(x, str) else x for x in v] for k, v in self._listas()},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]

    def _listas(self) -> Iterator[tuple[str, list]]:  # type: ignore[type-arg]
        yield from (
            ("entidades", self.entidades),
            ("fatos", self.fatos),
            ("arestas", self.arestas),
            ("conversa", self.conversa),
            ("consultas", self.consultas),
        )

    def dividir(self, fracao: float = 0.7, semente: int = SEMENTE) -> tuple[set[str], set[str]]:
        """70% para calibrar, 30% retidos para reportar (§8.2, regra 7), estratificado."""
        rng = random.Random(semente + 1)  # noqa: S311 — sorteia a divisão, não segredo
        calibracao: set[str] = set()
        retidas: set[str] = set()
        for sub in ("C2a", "C2b", "C2c", "C2d"):
            ids = sorted(c.id for c in self.consultas if c.subconjunto == sub)
            rng.shuffle(ids)
            corte = round(len(ids) * fracao)
            calibracao.update(ids[:corte])
            retidas.update(ids[corte:])
        return calibracao, retidas


def _o(artigo: str) -> str:
    return "A" if artigo == "a" else "O"


def _meu(artigo: str) -> str:
    return "minha" if artigo == "a" else "meu"


def _slug(texto: str) -> str:
    sem = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return "-".join("".join(ch if ch.isalnum() else " " for ch in sem.casefold()).split())


PESSOAS: Final = (
    # nome, apelido, relação (a relação também resolve para a pessoa: "minha irmã" → Beatriz)
    ("Beatriz", "Bia", "irmã", "a"),
    ("Fernando", "Nando", "sócio", "o"),
    ("Mariana", "Mari", "esposa", "a"),
    ("Rodrigo", "Digão", "cunhado", "o"),
    ("Luís Henrique", "LH", "contador", "o"),
    ("Gabriela", "Gabi", "designer", "a"),
    ("Joaquim", "Quinzinho", "primo", "o"),
    ("Antônia", "Tonha", "tia", "a"),
    ("Eduardo", "Dudu", "vizinho", "o"),
    ("Patrícia", "Pati", "advogada", "a"),
    ("Ricardo", "Rick", "chefe", "o"),
    ("Vanessa", "Nessa", "estagiária", "a"),
    ("Francisco", "Chico", "padrinho", "o"),
    ("Juliana", "Ju", "cliente da agência", "a"),
)
CLIENTES: Final = (
    ("Construtora Sol", "Sol"),
    ("Padaria Trigo Bom", "Trigo Bom"),
    ("Clínica Vida Plena", "Vida Plena"),
    ("Agência Nogueira", "Nogueira"),
    ("Loja Bom Preço", "Bom Preço"),
    ("Academia Corpo Ativo", "Corpo Ativo"),
    ("Pousada Mar Azul", "Mar Azul"),
    ("Oficina Roda Viva", "Roda Viva"),
    ("Floricultura Ipê", "Ipê"),
    ("Escola Pequeno Saber", "Pequeno Saber"),
)
ASSUNTOS: Final = (
    ("proposta", "a", "ods"),
    ("orçamento", "o", "ods"),
    ("contrato", "o", "pdf"),
    ("cronograma", "o", "ods"),
    ("relatório mensal", "o", "pdf"),
    ("logotipo", "o", "svg"),
    ("cardápio", "o", "pdf"),
    ("planilha de custos", "a", "ods"),
    ("apresentação", "a", "odp"),
    ("nota fiscal", "a", "pdf"),
)
DIAS: Final = ("segunda", "terça", "quarta", "quinta", "sexta")
APPS: Final = (
    "Inkscape",
    "GIMP",
    "Krita",
    "Blender",
    "Kdenlive",
    "LibreOffice Writer",
    "LibreOffice Calc",
    "Obsidian",
    "Figma",
    "Audacity",
)
ENTREGAS: Final = (
    "panfleto",
    "cartaz",
    "vídeo institucional",
    "post para rede social",
    "banner do site",
    "jingle",
    "modelo 3D",
    "manual de marca",
    "folder",
    "convite",
    "cardápio digital",
    "catálogo",
)
OCASIOES: Final = ("de inverno", "de Natal", "de aniversário", "da inauguração", "de verão")
PREFERENCIAS: Final = (
    # (fato do dono, pergunta parafraseada) — C2a, o dono como sujeito
    ("Uso o Visual Studio Code como editor de código padrão.", "qual é o meu editor de código?"),
    ("Minhas notas pessoais ficam todas no Obsidian.", "onde eu guardo minhas anotações?"),
    ("Escuto música trabalhando pelo Spotify.", "que app eu uso para ouvir música?"),
    ("Meus e-mails eu leio no Thunderbird.", "qual programa de e-mail eu uso?"),
    ("Banco de dados eu abro sempre pelo DBeaver.", "com que ferramenta eu mexo no banco?"),
    ("Meu café é coado, sem açúcar, de manhã cedo.", "como eu gosto do meu café?"),
    ("Treino na academia às 7 da manhã, de segunda a sexta.", "que horas eu malho?"),
    ("Minha comida preferida é moqueca de peixe.", "qual o meu prato favorito?"),
    ("Durmo melhor com o quarto bem escuro e o ventilador ligado.", "como eu durmo melhor?"),
    (
        "Prefiro reunião de manhã; depois do almoço eu rendo menos.",
        "que horário eu prefiro para reuniões?",
    ),
    ("Meu teclado é mecânico com switch marrom.", "que teclado eu tenho?"),
    ("Uso o tema escuro em todos os programas.", "eu prefiro tema claro ou escuro?"),
    (
        "Faço backup do notebook no HD externo todo domingo.",
        "quando eu faço cópia de segurança do notebook?",
    ),
    ("Meu sistema operacional é o Linux, com KDE.", "que sistema eu uso no computador?"),
    ("Leio livros pelo Kindle antes de dormir.", "como eu leio meus livros?"),
    ("Minha bebida de fim de semana é cerveja de trigo.", "o que eu gosto de beber no sábado?"),
    ("Corro no parque aos domingos de manhã.", "onde eu corro e quando?"),
    ("Minha série favorita é Dark.", "qual série eu mais gosto?"),
)
CODE_SWITCH: Final = (
    ("A reunião diária do time é às 9h30, por chamada de vídeo.", "que horas é a daily?"),
    ("Publico a versão nova do site toda sexta à noite.", "quando é o deploy do site?"),
    ("A cópia do servidor roda toda madrugada às 3h.", "que horas roda o backup do server?"),
    ("Revisão de código da equipe é na quarta à tarde.", "quando é o code review?"),
    (
        "O planejamento das próximas duas semanas é na segunda de manhã.",
        "quando é a sprint planning?",
    ),
    ("Os chamados de suporte eu respondo depois do almoço.", "quando eu olho os tickets?"),
)
SIGLAS: Final = (
    ("O imposto de renda deste ano eu entrego até 31 de maio.", "até quando eu entrego o IR?"),
    ("Meu CNPJ é de microempresa, no Simples Nacional.", "qual o regime da minha PJ?"),
    ("A carteira de motorista vence em agosto de 2028.", "quando vence minha CNH?"),
    ("O plano de saúde é pela empresa da Mariana.", "quem paga meu convênio médico?"),
)
TEMPORAIS: Final = (
    # (antes, depois, pergunta)
    (
        "Uso o Firefox como navegador.",
        "Agora uso o Brave como navegador.",
        "qual navegador eu uso?",
    ),
    (
        "Meu celular é um Motorola.",
        "Troquei de celular, agora é um Samsung.",
        "qual é o meu celular?",
    ),
    (
        "Treino de muay thai às terças.",
        "Larguei o muay thai e agora faço natação às terças.",
        "o que eu faço de esporte na terça?",
    ),
    (
        "Meu dentista é o doutor Paulo.",
        "Mudei de dentista: agora é a doutora Helena.",
        "quem é meu dentista?",
    ),
    (
        "Almoço no restaurante da esquina.",
        "Agora levo marmita e almoço no escritório.",
        "onde eu almoço?",
    ),
    (
        "Trabalho de casa às sextas.",
        "Agora trabalho de casa às quartas, não mais às sextas.",
        "que dia eu fico em casa trabalhando?",
    ),
    (
        "Meu carro é um Gol prata.",
        "Vendi o Gol; agora ando de moto, uma Biz vermelha.",
        "qual veículo eu tenho?",
    ),
    ("Durmo às 23h.", "Agora vou dormir à meia-noite.", "que horas eu vou dormir?"),
    (
        "Meu plano de celular é da Vivo.",
        "Mudei o plano do celular para a Claro.",
        "qual operadora eu uso?",
    ),
    (
        "A reunião com a Construtora Sol é toda quinta.",
        "A reunião com a Construtora Sol mudou para sexta.",
        "quando é a reunião com a Sol?",
    ),
    (
        "A reunião com a Padaria Trigo Bom é na segunda.",
        "A reunião com a Padaria Trigo Bom passou para terça.",
        "que dia eu encontro a Trigo Bom?",
    ),
    ("Pago o aluguel no dia 5.", "O aluguel agora vence no dia 10.", "que dia eu pago o aluguel?"),
)
NEGATIVOS: Final = (
    "qual é o meu time de futebol?",
    "qual o meu tipo sanguíneo?",
    "quando é o aniversário do Tadeu?",
    "o que a Ótica Visão Clara pediu?",
    "onde está o arquivo relatorio-anual-2019.pdf?",
    "qual é o nome do meu cachorro?",
    "em que cidade eu nasci?",
    "qual o meu número de sapato?",
    "quem é o meu oftalmologista?",
    "que instrumento eu toco?",
    "qual a marca da minha geladeira?",
    "quando eu viajei para o Japão?",
    "qual o nome da minha professora de inglês?",
    "que vinho eu comprei no mês passado?",
    "quem é o síndico do meu prédio?",
    "qual é a senha do roteador da casa da praia?",
    "qual o meu signo?",
    "quando é a formatura da Lúcia?",
    "o que o Bernardo mandou ontem?",
    "qual o modelo da minha bicicleta?",
)


def gerar(semente: int = SEMENTE) -> Corpus:
    rng = random.Random(semente)  # noqa: S311 — gera corpus, não segredo
    corpus = Corpus()
    fatos = corpus.fatos
    consultas = corpus.consultas

    def fato(texto: str, *, substitui: str | None = None) -> str:
        chave = f"f{len(fatos):04d}"
        fatos.append(Fato(chave=chave, texto=texto, substitui=substitui))
        return chave

    def consulta(
        sub: Subconjunto, texto: str, gabarito: tuple[str, ...], vencidos: tuple[str, ...] = ()
    ) -> None:
        consultas.append(
            Consulta(
                id=f"q{len(consultas):03d}",
                subconjunto=sub,
                texto=texto,
                gabarito=gabarito,
                vencidos=vencidos,
            )
        )

    # --- entidades ------------------------------------------------------------------------
    for nome, apelido, relacao, _ in PESSOAS:
        corpus.entidades.append(
            Entidade(
                nome, "pessoa", (apelido, f"meu {relacao}" if _ == "o" else f"minha {relacao}")
            )
        )
    for nome, apelido in CLIENTES:
        corpus.entidades.append(Entidade(nome, "organizacao", (apelido,)))
    for app in APPS:
        corpus.entidades.append(Entidade(app, "app"))

    # --- quem é quem (sustenta a resolução "minha irmã" → Beatriz) --------------------------
    for nome, _, relacao, artigo in PESSOAS:
        fato(f"{_o(artigo)} {nome} é {_meu(artigo)} {relacao}.")

    # --- C2a: preferências, code-switch e siglas -------------------------------------------
    for texto, pergunta in (*PREFERENCIAS, *CODE_SWITCH, *SIGLAS):
        consulta("C2a", pergunta, (fato(texto),))

    # --- C2a: fatos de pessoa, perguntados pelo apelido -------------------------------------
    meses = (
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    )
    cidades = (
        "Campinas",
        "Recife",
        "Curitiba",
        "Salvador",
        "Belo Horizonte",
        "Porto Alegre",
        "Natal",
        "Goiânia",
        "Florianópolis",
        "Manaus",
        "Vitória",
        "Fortaleza",
        "Cuiabá",
        "Belém",
    )
    hobbies = (
        "pintura em aquarela",
        "escalada",
        "xadrez",
        "jardinagem",
        "fotografia",
        "cerâmica",
        "violão",
        "corrida de rua",
        "marcenaria",
        "crochê",
        "surfe",
        "astronomia",
        "cozinha japonesa",
        "patinação",
    )
    sem_aniversario = {"Fernando", "Ricardo"}  # viram negativos difíceis (C2d)
    for i, (nome, apelido, _, artigo) in enumerate(PESSOAS):
        de = "da" if artigo == "a" else "do"
        if nome not in sem_aniversario:
            dia_do_mes = rng.randint(1, 28)
            consulta(
                "C2a",
                f"quando é o aniversário {de} {apelido}?",
                (fato(f"O aniversário {de} {nome} é em {dia_do_mes} de {meses[(i * 5) % 12]}."),),
            )
        consulta(
            "C2a",
            f"onde {'a' if artigo == 'a' else 'o'} {apelido} mora?",
            (fato(f"{'A' if artigo == 'a' else 'O'} {nome} mora em {cidades[i]}."),),
        )
        if i % 2 == 0:
            consulta(
                "C2a",
                f"qual é o passatempo {de} {apelido}?",
                (fato(f"{_o(artigo)} {nome} gosta de {hobbies[i]} nas horas vagas."),),
            )
        else:
            fato(f"{'A' if artigo == 'a' else 'O'} {nome} gosta de {hobbies[i]} nas horas vagas.")

    # --- C2b/T1: quem mandou qual arquivo sobre o quê --------------------------------------
    arquivos: list[tuple[str, str, str, str, str]] = []  # (arquivo, pessoa, cliente, assunto, dia)
    for c, (cliente, _) in enumerate(CLIENTES):
        for a, (assunto, _, ext) in enumerate(ASSUNTOS):
            for versao in (1, 2, 3):
                pessoa = PESSOAS[(c * 7 + a * 3 + versao * 5) % len(PESSOAS)][0]
                nome = f"{_slug(assunto)}-{_slug(cliente.split()[-1])}-v{versao}.{ext}"
                arquivos.append((nome, pessoa, cliente, assunto, DIAS[(c + a + versao) % 5]))
    rng.shuffle(arquivos)
    por_arquivo: dict[str, tuple[str, str]] = {}
    for nome, pessoa, cliente, assunto, dia in arquivos:
        corpus.entidades.append(Entidade(nome, "arquivo"))
        artigo = next(p[3] for p in PESSOAS if p[0] == pessoa)
        envio = fato(f"{'A' if artigo == 'a' else 'O'} {pessoa} mandou o {nome} na {dia}.")
        art_assunto = next(s[1] for s in ASSUNTOS if s[0] == assunto)
        sobre = fato(f"O {nome} é {art_assunto} {assunto} da {cliente}.")
        corpus.arestas.append(Aresta(pessoa, "enviou", nome, envio))
        corpus.arestas.append(Aresta(nome, "sobre", cliente, sobre))
        por_arquivo[nome] = (envio, sobre)

    # perguntas multi-salto: pela relação (não pelo nome) e pelo apelido do cliente
    vistos: set[tuple[str, str, str]] = set()
    candidatos = [x for x in arquivos]
    rng.shuffle(candidatos)
    for nome, pessoa, cliente, assunto, _dia in candidatos:
        chave = (pessoa, cliente, assunto)
        mesmos = [x for x in arquivos if (x[1], x[2], x[3]) == chave]
        if chave in vistos or len(mesmos) != 1:
            continue  # a pergunta tem de ter uma resposta só
        vistos.add(chave)
        _, _, relacao, artigo = next(p for p in PESSOAS if p[0] == pessoa)
        apelido_cliente = next(c[1] for c in CLIENTES if c[0] == cliente)
        art_assunto = next(s[1] for s in ASSUNTOS if s[0] == assunto)
        quem = f"{'minha' if artigo == 'a' else 'meu'} {relacao}"
        consulta(
            "C2b",
            f"qual arquivo {quem} mandou sobre {art_assunto} {assunto} da {apelido_cliente}?",
            por_arquivo[nome],
        )
        if len(vistos) >= 30:
            break

    # --- C2b/T2: o que o cliente pediu → com que app eu faço -------------------------------
    pedidos: list[tuple[str, str, str]] = []
    for c, (cliente, _) in enumerate(CLIENTES):
        for j in range(4):
            tipo_da_entrega = ENTREGAS[(c * 4 + j) % len(ENTREGAS)]
            entrega = (
                f"{tipo_da_entrega} {OCASIOES[(c + j) % len(OCASIOES)]} da {cliente.split()[-1]}"
            )
            app = APPS[(c * 3 + j * 7) % len(APPS)]
            pedidos.append((cliente, entrega, app))
    for n, (cliente, entrega, app) in enumerate(pedidos):
        corpus.entidades.append(Entidade(entrega, "entrega"))
        pedido = fato(f"A {cliente} pediu o {entrega}.")
        feito = fato(f"O {entrega} eu estou fazendo no {app}.")
        corpus.arestas.append(Aresta(cliente, "pediu", entrega, pedido))
        corpus.arestas.append(Aresta(entrega, "feito_com", app, feito))
        if n % 4 == 0:  # um pedido por cliente vira pergunta, perguntado pelo apelido
            apelido_cliente = next(c[1] for c in CLIENTES if c[0] == cliente)
            tipo = entrega.split(" de ")[0].split(" da ")[0]
            consulta(
                "C2b",
                f"em que programa eu faço o {tipo} que a {apelido_cliente} pediu?",
                (feito, pedido),
            )

    # --- C2b/T3: pessoa → empresa onde trabalha → vencimento do contrato --------------------
    vencimentos = {}
    for c, (cliente, _) in enumerate(CLIENTES):
        vencimentos[cliente] = fato(
            f"O contrato com a {cliente} vence em {meses[(c * 7) % 12]} de 2027."
        )
    for i, (nome, _, relacao, artigo) in enumerate(PESSOAS[:10]):
        cliente = CLIENTES[(i * 3) % len(CLIENTES)][0]
        trabalha = fato(f"{'A' if artigo == 'a' else 'O'} {nome} trabalha na {cliente}.")
        corpus.arestas.append(Aresta(nome, "trabalha_em", cliente, trabalha))
        quem = f"{'minha' if artigo == 'a' else 'meu'} {relacao}"
        consulta(
            "C2b",
            f"quando vence o contrato da empresa onde {quem} trabalha?",
            (vencimentos[cliente], trabalha),
        )

    # --- C2c: o que mudou ------------------------------------------------------------------
    for antes, depois, pergunta in TEMPORAIS:
        velho = fato(antes)
        novo = fato(depois, substitui=velho)
        consulta("C2c", pergunta, (novo,), (velho,))
    for i, (nome, apelido, _, artigo) in enumerate(PESSOAS[10:]):
        de_cliente = CLIENTES[(i * 3 + 1) % len(CLIENTES)][0]
        para_cliente = CLIENTES[(i * 3 + 2) % len(CLIENTES)][0]
        velho = fato(f"{'A' if artigo == 'a' else 'O'} {nome} trabalha na {de_cliente}.")
        novo = fato(
            f"{_o(artigo)} {nome} saiu da {de_cliente} e agora trabalha na {para_cliente}.",
            substitui=velho,
        )
        consulta(
            "C2c",
            f"onde {'a' if artigo == 'a' else 'o'} {apelido} trabalha hoje?",
            (novo,),
            (velho,),
        )

    cursos = (
        "inglês",
        "espanhol",
        "piano",
        "programação",
        "contabilidade",
        "design gráfico",
        "francês",
        "fotografia digital",
        "culinária",
        "alemão",
        "libras",
        "marketing",
        "violino",
        "italiano",
    )
    for i, (nome, apelido, _, artigo) in enumerate(PESSOAS):
        o = "A" if artigo == "a" else "O"
        velho = fato(f"{o} {nome} está fazendo curso de {cursos[i]}.")
        novo = fato(
            f"{o} {nome} terminou o curso de {cursos[i]} e começou um de "
            f"{cursos[(i + 5) % len(cursos)]}.",
            substitui=velho,
        )
        consulta("C2c", f"que curso {o.lower()} {apelido} está fazendo agora?", (novo,), (velho,))

    # --- C2d: negativos, inclusive os difíceis ---------------------------------------------
    for pergunta in NEGATIVOS:
        consulta("C2d", pergunta, ())
    for nome in sorted(sem_aniversario):
        apelido = next(p[1] for p in PESSOAS if p[0] == nome)
        consulta("C2d", f"quando é o aniversário do {apelido}?", ())
    for _cliente, apelido in CLIENTES[:6]:
        consulta("C2d", f"qual é o telefone de contato da {apelido}?", ())
    for _nome, apelido, _, artigo in PESSOAS[:6]:
        consulta("C2d", f"qual é a cor preferida {'da' if artigo == 'a' else 'do'} {apelido}?", ())

    # --- conversa à toa (turnos, não memória) ----------------------------------------------
    coisas = (
        "o trânsito",
        "a chuva",
        "o almoço",
        "a internet",
        "o calor",
        "o jogo de ontem",
        "a fila do banco",
        "o barulho da obra",
    )
    estados = (
        "estava terrível",
        "foi tranquilo",
        "me atrasou",
        "melhorou",
        "piorou de novo",
        "rendeu conversa",
    )
    for n in range(1500):
        corpus.conversa.append(
            f"{coisas[n % len(coisas)].capitalize()} hoje {estados[(n * 7) % len(estados)]}, "
            f"{rng.choice(('né', 'viu', 'sério', 'enfim'))}. ({n})"
        )
    return corpus


# --- o corpus dentro do livro de verdade ------------------------------------------------
@dataclass(slots=True)
class Montado:
    """O livro montado do corpus, com o gabarito traduzido para `memory_unit`."""

    livro: Any
    instante: str
    unidade_do_fato: dict[str, str]
    itens: list[Any]
    """O que a outbox mandou indexar, na ordem — o §8.1 indexa isto nos dois candidatos."""

    def gabarito(self, consulta: Consulta) -> set[str]:
        return {self.unidade_do_fato[f] for f in consulta.gabarito}

    def vencidos(self, consulta: Consulta) -> set[str]:
        return {self.unidade_do_fato[f] for f in consulta.vencidos}


@dataclass(slots=True)
class _Coletor:
    """Índice que só anota o que receberia — para indexar depois, em outro processo."""

    destino: Any
    itens: list[Any] = field(default_factory=list)

    def upsert(self, itens: Any) -> int:
        self.itens.extend(itens)
        return int(self.destino.upsert(itens))

    def delete(self, ids: Any) -> int:
        return int(self.destino.delete(ids))

    def search(self, query: str, k: int, onde: Any = None) -> Any:
        return self.destino.search(query, k, onde)

    def stats(self) -> Any:
        return self.destino.stats()


def montar(corpus: Corpus, indice: Any, *, caminho: str = ":memory:") -> Montado:
    """Grava o corpus pela API do livro (as mesmas invariantes do produto) e indexa a outbox."""
    from datetime import UTC, datetime, timedelta

    from jarvis.memoryd.cofre import CofreFernet, nova_chave
    from jarvis.memoryd.livro import LivroDeMemoria
    from jarvis.memoryd.sintetico import atualizar_graus
    from jarvis.politica.memoria import Estado, normalizar

    relogio = {"agora": datetime(2026, 8, 1, 9, 0, tzinfo=UTC)}

    def agora() -> datetime:
        relogio["agora"] += timedelta(minutes=7)
        return relogio["agora"]

    coletor = _Coletor(indice)
    livro = LivroDeMemoria.abrir(
        caminho, cofre=CofreFernet(nova_chave()), indice=coletor, agora=agora
    )
    sessao = "0193f0a0-0000-7000-8000-00000000c2c2"
    conversa = iter(corpus.conversa)
    episodio_do_fato: dict[str, str] = {}
    assertiva: dict[str, str] = {}
    for n, fato in enumerate(corpus.fatos):
        for _ in range(2 if n % 5 else 1):  # conversa à toa intercalada
            texto = next(conversa, None)
            if texto is not None:
                livro.gravar_turno(session_id=sessao, papel="dono", texto=texto, trust="user_voice")
        ep = livro.gravar_turno(
            session_id=sessao, papel="dono", texto=fato.texto, trust="user_voice"
        )
        episodio_do_fato[fato.chave] = ep
        if fato.substitui:
            feito = livro.atualizar(assertiva[fato.substitui], fato.texto, motivo="mudou", fonte=ep)
        else:
            feito = livro.lembrar(fato.texto, estado=Estado.ATIVA, fonte=ep, extrator="dono")
        assertiva[fato.chave] = feito["assertion_id"]
    for texto in conversa:
        livro.gravar_turno(session_id=sessao, papel="dono", texto=texto, trust="user_voice")

    textos = {f.chave: f" {normalizar(f.texto)} " for f in corpus.fatos}
    for entidade in corpus.entidades:
        nomes = [normalizar(x) for x in (entidade.nome, *entidade.apelidos)]
        fonte = next(
            (episodio_do_fato[c] for c, t in textos.items() if any(f" {x} " in t for x in nomes)),
            episodio_do_fato[corpus.fatos[0].chave],
        )
        livro.criar_no(
            entidade.tipo,
            entidade.nome,
            apelidos=entidade.apelidos,
            estado=Estado.ATIVA,
            fonte=fonte,
            extrator="gabarito",
        )
    for aresta in corpus.arestas:
        livro.criar_aresta(
            aresta.origem,
            aresta.relacao,
            aresta.destino,
            estado=Estado.ATIVA,
            fonte=episodio_do_fato[aresta.fato],
            extrator="gabarito",
        )
    livro.processar_outbox()
    atualizar_graus(livro.con)
    unidade_do_fato = {
        chave: str(
            livro.con.execute(
                "SELECT id FROM memory_unit WHERE assertion_id = ?", (assertiva[chave],)
            ).fetchone()["id"]
        )
        for chave in assertiva
    }
    return Montado(
        livro=livro,
        instante=(relogio["agora"] + timedelta(minutes=1))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        unidade_do_fato=unidade_do_fato,
        itens=coletor.itens,
    )
