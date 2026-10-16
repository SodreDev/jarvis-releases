"""TTS na ElevenLabs: o texto que o Jarvis vai falar saindo da máquina (ADR-0017).

Mesmo desenho do adaptador da Groq — portão, chave no cabeçalho, prazo nosso, degradação
declarada, pedaço em voo descartado —, com três diferenças que são do serviço e não do código:

1. **O cabeçalho da chave é `xi-api-key`**, não `Authorization: Bearer`;
2. **A resposta é áudio cru, não JSON.** Com `output_format=pcm_16000` o serviço devolve
   PCM16 16 kHz mono — exatamente o formato do caminho de áudio deste produto (F1-01), então
   não há reamostragem nem decodificação no meio;
3. **A retenção é o oposto da Groq.** A ElevenLabs retém por padrão: *"Customers by default
   have history preservation enabled"*, e o Zero Retention Mode (`enable_logging=false`) é
   *"Enterprise customers can use Zero Retention Mode"* (lido em 2026-10-15). Por isso
   `retencao_zero` existe, nasce **desligada** e é decisão do dono: mandar o parâmetro numa
   conta comum é pedir ao serviço que recuse o pedido inteiro.

O que o dono precisa ler antes de ligar está em `licenses/motores.toml` e sai em uma frase por
`aviso` — inclusive o que o plano gratuito proíbe (*"you may only use the Services for
non-commercial purposes"*).
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.rede import AdaptadorRemoto, Sonda, SondaInjetada
from jarvis.voz.chaves import VARIAVEL_ELEVENLABS, Chave
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.nuvem import ClienteHttp, ServicoRecusou, proibir_nuvem_real_em_ci
from jarvis.voz.registro import Motor, MotorRecusado, exigir_modelo, exigir_motor

BASE_PADRAO: Final = "https://api.elevenlabs.io"
CAMINHO_FALA: Final = "/v1/text-to-speech"
MODELO_PADRAO: Final = "eleven_multilingual_v2"
FORMATO: Final = f"pcm_{TAXA_PADRAO}"
"""`pcm_16000`: o mesmo PCM16 16 kHz mono do `audio-io`. Nada de mp3 para decodificar."""
CABECALHO_DA_CHAVE: Final = "xi-api-key"
PRAZO_PADRAO_S: Final = 10.0
SERVICO: Final = "ElevenLabs"
REGISTRADO: Final = "tts-elevenlabs"
CAMINHO_VOZES: Final = "/v2/voices"
"""Lista as vozes da conta (https://elevenlabs.io/docs/api-reference/voices/search, lida em
2026-10-16): `page_size` até 100, paginação por `has_more` + `next_page_token`."""
VOZES_POR_PAGINA: Final = 100
PAGINAS_NO_MAXIMO: Final = 5
"""Teto nosso: 500 vozes é mais do que uma conta pessoal tem, e consulta sem teto é laço na
mão de um terceiro."""
FORMA_DO_ID: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(slots=True)
class MotorTtsElevenLabs:
    """Voz da ElevenLabs atrás da mesma interface do piper local."""

    raiz: Path
    voz: str = ""
    """O `voice_id` da conta do dono. Vem da configuração dele; não há padrão inventado."""
    modelo: str = MODELO_PADRAO
    registrado: str = REGISTRADO
    base: str = BASE_PADRAO
    nuvem_ligada: Collection[str] = ()
    cancelado: Cancelado = nunca_cancelado
    prazo_s: float = PRAZO_PADRAO_S
    retencao_zero: bool = False
    """`enable_logging=false`. Só Enterprise: ligar numa conta comum faz o serviço recusar."""
    sonda: Sonda | None = None
    ambiente: Mapping[str, str] | None = None

    nome: str = ""
    licenca: str = ""
    onde: Onde = Onde.NUVEM
    sinteses: int = 0
    descartadas_por_cancelamento: int = 0
    caracteres_enviados: int = 0
    """Quanto texto já saiu da máquina. É o que o dono vê no diagnóstico — e o que a conta
    dele cobra, porque a ElevenLabs cobra por caractere."""
    _motor: Motor | None = field(default=None, repr=False)
    _chave: Chave | None = field(default=None, repr=False)
    _cliente: ClienteHttp | None = field(default=None, repr=False)
    _adaptador: AdaptadorRemoto | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.nome:
            self.nome = f"elevenlabs@{self.modelo}"

    def abrir(self) -> Motor:
        motor = exigir_motor(self.registrado, nuvem_ligada=self.nuvem_ligada)
        self.licenca = motor.licenca_do_cliente
        self._motor = motor
        if not self.voz:
            raise MotorRecusado(
                "motor 'tts-elevenlabs' sem voz escolhida: o `voice_id` é da conta do dono e "
                "vem da configuração dele. Nenhum padrão é inventado aqui — voz é escolha de "
                "ouvido, e a conta é dele"
            )
        if not FORMA_DO_ID.fullmatch(self.voz):
            raise MotorRecusado(
                f"voz {self.voz!r} não tem a forma de um voice_id da ElevenLabs (letras, "
                "números, _ e -): ele vai no caminho da URL"
            )
        self.modelo = exigir_modelo(motor, self.modelo)
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
        motor = self._motor or exigir_motor(self.registrado, nuvem_ligada=[self.registrado])
        return motor.frase_de_aviso

    @property
    def degradado(self) -> bool:
        return self._adaptador is not None and self._adaptador.degradado

    def sintetizar(self, texto: str) -> bytes:
        """PCM16 16 kHz do trecho. Vazio quando cancela ou quando a rede cai.

        Vazio **não** é silêncio enfileirado: o `SintetizadorEmStreaming` do F1-09 vê o
        cancelamento e não enfileira nada, e a fila de playback não recebe pedaço fantasma.
        """
        if self._cliente is None or self._chave is None or self._adaptador is None:
            self.abrir()
        cliente, chave, adaptador = self._cliente, self._chave, self._adaptador
        assert cliente is not None and chave is not None and adaptador is not None

        if self.cancelado():
            self.descartadas_por_cancelamento += 1
            return b""

        self.sinteses += 1
        self.caracteres_enviados += len(texto)
        call_id = f"tts-elevenlabs-{self.sinteses}"
        corpo = json.dumps({"text": texto, "model_id": self.modelo}).encode("utf-8")
        consulta = f"?output_format={FORMATO}"
        if self.retencao_zero:
            consulta += "&enable_logging=false"

        def fazer(prazo: float) -> bytes | None:
            resposta = cliente.postar(
                f"{CAMINHO_FALA}/{self.voz}{consulta}",
                corpo=corpo,
                tipo_do_corpo="application/json",
                chave=chave,
                cabecalho_da_chave=CABECALHO_DA_CHAVE,
                prefixo_da_chave="",
                cancelado=self.cancelado,
                prazo_s=prazo,
            )
            if resposta.cancelada:
                self.descartadas_por_cancelamento += 1
                return None
            return _amostras_de(resposta.corpo)

        amostras = adaptador.chamar(fazer, call_id=call_id)
        return amostras if amostras is not None else b""


def _amostras_de(corpo: bytes) -> bytes:
    """O corpo como PCM16, recusando o que não for.

    Um byte ímpar não é PCM16 — é mp3, JSON de erro com status 200 ou corpo truncado. Tocar
    isso entregaria chiado ao dono; recusar entrega uma frase que ele entende.

    É `ServicoRecusou`, não `ErroDoServico`: corpo malformado **não** é queda de rede, e virar
    degradação esconderia o problema atrás de "caí para o botão de falar". O dono tem de ler
    que o formato ou o plano estão errados.
    """
    if len(corpo) % BYTES_POR_AMOSTRA != 0:
        raise ServicoRecusou(
            f"o serviço devolveu {len(corpo)} bytes, que não é PCM16 ({BYTES_POR_AMOSTRA} "
            f"bytes por amostra): confira o `output_format={FORMATO}` e o plano da conta"
        )
    return corpo


@dataclass(frozen=True, slots=True)
class VozDaConta:
    """Uma voz que a conta do dono enxerga. Dado de catálogo: nada aqui é segredo."""

    id: str
    nome: str
    categoria: str = ""
    idiomas: tuple[str, ...] = ()

    @property
    def fala_portugues(self) -> bool:
        return any(idioma.lower().startswith("pt") for idioma in self.idiomas)

    def para_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "nome": self.nome,
            "categoria": self.categoria,
            "idiomas": list(self.idiomas),
            "portugues": self.fala_portugues,
        }


def listar_vozes(
    *,
    ambiente: Mapping[str, str] | None = None,
    base: str = BASE_PADRAO,
    prazo_s: float = PRAZO_PADRAO_S,
    cliente: ClienteHttp | None = None,
) -> tuple[VozDaConta, ...]:
    """As vozes da conta do dono, as de português primeiro.

    Só o dono dispara isto (botão ou tela de configuração): é uma consulta de catálogo com a
    chave dele no cabeçalho — **nenhum texto ou áudio dele sai** —, e por isso não depende do
    interruptor da nuvem. A chave vem do mesmo caminho do motor (`Chave.do_ambiente`, que a
    janela alimenta com o chaveiro); a resposta não carrega chave e o erro passa por `redigir`.
    """
    proibir_nuvem_real_em_ci(base, ambiente)
    chave = Chave.do_ambiente(VARIAVEL_ELEVENLABS, ambiente=ambiente)
    http = cliente or ClienteHttp(base=base, prazo_s=prazo_s, ambiente=ambiente)
    vozes: list[VozDaConta] = []
    ficha = ""
    for _ in range(PAGINAS_NO_MAXIMO):
        consulta = f"?page_size={VOZES_POR_PAGINA}&include_total_count=false"
        if ficha:
            consulta += f"&next_page_token={urllib.parse.quote(ficha, safe='')}"
        resposta = http.obter(
            f"{CAMINHO_VOZES}{consulta}",
            chave=chave,
            cabecalho_da_chave=CABECALHO_DA_CHAVE,
            prefixo_da_chave="",
        )
        dados = resposta.json()
        vozes += [v for v in map(_voz_de, dados.get("voices") or []) if v is not None]
        ficha = str(dados.get("next_page_token") or "")
        if not dados.get("has_more") or not ficha:
            break
    unicas = {voz.id: voz for voz in vozes}
    return tuple(sorted(unicas.values(), key=lambda v: (not v.fala_portugues, v.nome.lower())))


def _voz_de(bruta: object) -> VozDaConta | None:
    """Uma voz da resposta, ou `None` se ela não serve para ir no caminho da URL."""
    if not isinstance(bruta, dict):
        return None
    identificador = str(bruta.get("voice_id", ""))
    if not FORMA_DO_ID.fullmatch(identificador):
        return None
    idiomas: list[str] = []
    for verificado in bruta.get("verified_languages") or []:
        if isinstance(verificado, dict) and verificado.get("language"):
            idiomas.append(str(verificado["language"]))
    rotulos = bruta.get("labels")
    if isinstance(rotulos, dict) and rotulos.get("language"):
        idiomas.append(str(rotulos["language"]))
    return VozDaConta(
        id=identificador,
        nome=str(bruta.get("name") or identificador)[:80],
        categoria=str(bruta.get("category") or ""),
        idiomas=tuple(dict.fromkeys(idiomas)),
    )
