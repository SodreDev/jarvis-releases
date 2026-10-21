"""ASR na Groq: aceleração opcional, e o áudio do dono saindo da máquina (ADR-0017).

É o primeiro caminho do produto em que **dado do dono sai do computador dele**, e o desenho
trata isso como mudança de natureza, não como ajuste de configuração:

- o motor **não abre** sem o interruptor do dono (`exigir_motor` com `nuvem_ligada`), e o
  registro nasce com ele desligado;
- `frase_de_aviso` — montada dos campos de termo do registro — é o que a UI mostra antes;
- a chave vem do ambiente (`JARVIS_GROQ_API_KEY`), vai **no cabeçalho** e não aparece em log,
  em evento, em `argv` nem em configuração (`jarvis.voz.chaves`);
- cada chamada passa pelo `AdaptadorRemoto` do F1-14: prazo nosso, queda **declarada** em uma
  frase, e pedido que caiu **não** é refeito (regra 5 da §3.3, "nada pendurado");
- cancelamento tem duas chances de parar: antes de abrir o socket (epoch morto não paga
  requisição) e entre pedaços do corpo da resposta, caso em que o que chegou é descartado.

**O que o dono paga, dito em número:** a Groq cobra no mínimo 10 s por requisição. Um turno de
voz quase sempre é mais curto do que isso, então `requisicoes_abaixo_do_minimo` conta quantas
vezes isso aconteceu — é o que o `--diagnostico` mostra para a conta não ser surpresa.

**O que este módulo não faz:** não escolhe entre `whisper-large-v3` e o `turbo` (é medição do
F1-16, e os dois estão registrados), não guarda áudio e não tenta de novo sozinho.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.rede import AdaptadorRemoto, Sonda, SondaInjetada
from jarvis.voz.chaves import Chave
from jarvis.voz.interface import Cancelado, Hipotese, Onde, Sinais, Transcricao, nunca_cancelado
from jarvis.voz.nuvem import (
    ClienteHttp,
    campos_sem_segredo,
    corpo_multipart,
    envelope_wav,
    proibir_nuvem_real_em_ci,
)
from jarvis.voz.registro import Motor, exigir_motor

BASE_PADRAO: Final = "https://api.groq.com/openai/v1"
CAMINHO_TRANSCRICAO: Final = "/audio/transcriptions"
MODELO_PADRAO: Final = "whisper-large-v3-turbo"
SEGUNDOS_MINIMOS_COBRADOS: Final = 10.0
"""Da página de preço: "If you submit a request less than this, you will still be billed for
10 seconds" (lida em 2026-10-15)."""
PRAZO_PADRAO_S: Final = 10.0
"""Prazo de uma transcrição de turno. Não é SLO: é o teto que impede espera indefinida."""
SERVICO: Final = "Groq"


@dataclass(slots=True)
class MotorAsrGroq:
    """`whisper` na Groq, atrás da mesma interface do motor local.

    `raiz` é a pasta de sessão: é onde a degradação é declarada (`degradacao.json`), para a
    `ui` desligar a escuta contínua e cair no PTT sem este módulo saber o que é uma tela.
    """

    raiz: Path
    modelo: str = MODELO_PADRAO
    registrado: str = ""
    base: str = BASE_PADRAO
    idioma: str = "pt"
    nuvem_ligada: Collection[str] = ()
    """Os motores de nuvem que **o dono** ligou na configuração dele. Vazio = nada liga."""
    cancelado: Cancelado = nunca_cancelado
    prazo_s: float = PRAZO_PADRAO_S
    sonda: Sonda | None = None
    ambiente: Mapping[str, str] | None = None

    nome: str = ""
    licenca: str = ""
    onde: Onde = Onde.NUVEM
    requisicoes_abaixo_do_minimo: int = 0
    descartadas_por_cancelamento: int = 0
    transcricoes: int = 0
    _motor: Motor | None = field(default=None, repr=False)
    _chave: Chave | None = field(default=None, repr=False)
    _cliente: ClienteHttp | None = field(default=None, repr=False)
    _adaptador: AdaptadorRemoto | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.registrado:
            self.registrado = f"asr-groq-{self.modelo}"
        if not self.nome:
            self.nome = f"groq@{self.modelo}"

    # --- abertura: portão, chave, e só então rede ---------------------------------------
    def abrir(self) -> Motor:
        """Portão → chave → cliente. Nenhum socket é aberto aqui.

        A ordem é a da ADR-0017: primeiro "este motor pode rodar e o dono ligou?", depois
        "existe chave?". Ao contrário, o produto pediria chave para um motor que nem roda.
        """
        motor = exigir_motor(self.registrado, nuvem_ligada=self.nuvem_ligada)
        self.licenca = motor.licenca_do_cliente
        self._motor = motor
        proibir_nuvem_real_em_ci(self.base, self.ambiente)
        self._chave = Chave.do_ambiente(motor.variavel_da_chave, ambiente=self.ambiente)
        self._cliente = ClienteHttp(base=self.base, prazo_s=self.prazo_s, ambiente=self.ambiente)
        self._adaptador = AdaptadorRemoto(
            servico=SERVICO,
            raiz=self.raiz,
            sonda=self.sonda if self.sonda is not None else SondaInjetada(ligada=True),
            prazo_s=self.prazo_s,
        )
        return motor

    @property
    def aviso(self) -> str:
        """O que a UI mostra antes de ligar este motor — vem do registro, não daqui."""
        motor = self._motor or exigir_motor(self.registrado, nuvem_ligada=[self.registrado])
        return motor.frase_de_aviso

    @property
    def degradado(self) -> bool:
        return self._adaptador is not None and self._adaptador.degradado

    # --- transcrição --------------------------------------------------------------------
    def transcrever(self, amostras: bytes) -> Hipotese:
        """Transcreve um bloco. Devolve hipótese vazia quando cancela ou quando a rede cai.

        Hipótese vazia **não** é "o dono não falou": é "não temos resposta". Quem decide o que
        fazer com isso é o `agentd` — e com a rede fora ele já tem a degradação declarada em
        arquivo, que é o caminho do F1-14 (cai para PTT e diz isso).
        """
        return self.transcrever_com_sinais(amostras).hipotese

    def transcrever_com_sinais(self, amostras: bytes) -> Transcricao:
        """O mesmo, com os sinais dos segmentos do `verbose_json` (`no_speech_prob`,
        `avg_logprob`, `compression_ratio`) — os que o filtro de ruído usa (ADR-0043)."""
        if self._cliente is None or self._chave is None or self._adaptador is None:
            self.abrir()
        cliente, chave, adaptador = self._cliente, self._chave, self._adaptador
        assert cliente is not None and chave is not None and adaptador is not None

        if self.cancelado():
            self.descartadas_por_cancelamento += 1
            return Transcricao(Hipotese("", 0.0))

        segundos = len(amostras) / 2 / 16000
        if 0 < segundos < SEGUNDOS_MINIMOS_COBRADOS:
            self.requisicoes_abaixo_do_minimo += 1

        campos = {
            "model": self.modelo,
            "language": self.idioma,
            "response_format": "verbose_json",
            "temperature": "0",
        }
        campos_sem_segredo(campos, [chave])
        corpo, tipo = corpo_multipart(
            campos, nome_do_arquivo="turno.wav", conteudo=envelope_wav(amostras)
        )

        self.transcricoes += 1
        # `call_id` é contador do motor, não `id()` do objeto: a regra 5 do §3.3 ("pedido que
        # caiu não é refeito") guarda o id dos descartados, e `id()` de um `bytes` liberado é
        # reaproveitado pelo CPython — dois turnos diferentes acabariam com o mesmo id.
        call_id = f"asr-groq-{self.transcricoes}"

        def fazer(prazo: float) -> Transcricao | None:
            resposta = cliente.postar(
                CAMINHO_TRANSCRICAO,
                corpo=corpo,
                tipo_do_corpo=tipo,
                chave=chave,
                cancelado=self.cancelado,
                prazo_s=prazo,
            )
            if resposta.cancelada:
                self.descartadas_por_cancelamento += 1
                return None
            return _transcricao_de(resposta.json())

        # `ErroDoServico` (5xx, 429, transporte) é capturado **dentro** do adaptador e vira
        # degradação declarada; `ServicoRecusou` (chave inválida, plano, pedido errado) não é
        # `ErroDeRede` e atravessa de propósito: o dono precisa ler o motivo certo.
        resultado = adaptador.chamar(fazer, call_id=call_id)
        return resultado if resultado is not None else Transcricao(Hipotese("", 0.0))


def _hipotese_de(dados: dict[str, Any]) -> Hipotese:
    """Texto e confiança do `verbose_json` (sem os sinais: ver `_transcricao_de`)."""
    return _transcricao_de(dados).hipotese


def _numeros(segmentos: list[Any], campo: str) -> list[float]:
    """O campo numérico de cada segmento que o tem; o que veio torto fica de fora."""
    return [
        float(s[campo])
        for s in segmentos
        if isinstance(s, dict)
        and isinstance(s.get(campo), (int, float))
        and not isinstance(s.get(campo), bool)
    ]


def _transcricao_de(dados: dict[str, Any]) -> Transcricao:
    """Texto, confiança e sinais do `verbose_json`.

    A confiança vem da média de `avg_logprob` dos segmentos — a mesma conta do motor local,
    para os dois números serem comparáveis no relatório. Resposta sem segmento devolve
    confiança **0,0**, e isso quer dizer "não medida", não "ruim": quem publica tem de dizer
    qual dos dois casos é. Os sinais seguem a mesma regra: o que a resposta não trouxe fica
    `None` ("não sei"), nunca zero.
    """
    texto = str(dados.get("text", "")).strip()
    segmentos = dados.get("segments")
    if not texto:
        return Transcricao(Hipotese("", 0.0))
    if not isinstance(segmentos, list) or not segmentos:
        return Transcricao(Hipotese(texto, 0.0))
    logs = _numeros(segmentos, "avg_logprob")
    sem_fala = _numeros(segmentos, "no_speech_prob")
    compressao = _numeros(segmentos, "compression_ratio")
    media = sum(logs) / len(logs) if logs else None
    sinais = Sinais(
        sem_fala=max(sem_fala) if sem_fala else None,
        logprob=media,
        compressao=max(compressao) if compressao else None,
    )
    if media is None:
        return Transcricao(Hipotese(texto, 0.0), sinais)
    return Transcricao(Hipotese(texto, float(min(1.0, max(0.0, 2.718281828**media)))), sinais)
