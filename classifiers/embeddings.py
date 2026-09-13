# classifiers/embeddings.py — J.A.R.V.I.S.
# Classificador semântico com sentence-transformers (MiniLM-L6-v2).
# Roda entre a camada de regex e o LLM — ~5ms por query, zero chamadas de rede.
# Se sentence-transformers não estiver instalado, retorna ("", 0.0) silenciosamente.
# -*- coding: utf-8 -*-

from __future__ import annotations
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# ── Exemplos de intenções (5-12 frases por intent, em PT-BR) ─────────────────
# Adicione mais frases ao array para aumentar a precisão de um intent específico.
_INTENT_EXAMPLES: dict[str, list[str]] = {
    # Spotify
    "spotify_tocar": [
        "toca uma música", "coloca uma música", "play no spotify",
        "bota uma música pra tocar", "quero ouvir música",
        "toca jazz", "bota o spotify pra tocar", "quero ouvir alguma coisa",
        "toca o show tem que continuar", "coloca a música perfeita",
    ],
    "spotify_playlist": [
        "toca uma playlist de pagode", "coloca uma playlist",
        "bota uma playlist pra tocar", "play na playlist",
        "toque playlist de samba", "quero ouvir uma playlist",
        "coloca playlist", "toca minha playlist favorita",
        "ativa uma playlist de rock", "bota playlist do dia",
    ],
    "spotify_artista": [
        "toca músicas do Roberto Carlos", "coloca músicas da Ivete Sangalo",
        "bota o artista BK", "quero ouvir músicas do Anitta",
        "toca o cantor pagodinho", "músicas da banda Jota Quest",
    ],
    "spotify_pausar": [
        "pausa a música", "para a música", "silencia o spotify",
        "para de tocar", "pausa o spotify", "para tudo",
    ],
    "spotify_proxima": [
        "próxima música", "pula essa", "skip essa faixa",
        "vai para a próxima", "muda a música", "passa essa",
    ],
    "spotify_anterior": [
        "música anterior", "volta a música", "toca a de antes",
        "volta uma faixa", "retoma a anterior",
    ],
    "spotify_atual": [
        "qual música está tocando", "o que está tocando", "que música é essa",
        "qual é a faixa atual", "me diz que música toca",
    ],

    # Sistema
    "sys_screenshot": [
        "tira um print", "screenshot", "print da tela", "captura a tela",
        "printscreen", "bate um print", "faz um print",
    ],
    "sys_analise_tela": [
        "observe o que está na minha tela", "olhe minha tela e me diga",
        "analisa a tela", "o que você vê na minha tela", "descreva a tela",
        "leia o que está na tela", "o que tem na tela", "olha o que tá aqui",
    ],
    "sys_calc": [
        "quanto é 25 vezes 4", "calcula 500 dividido por 5",
        "me faz uma conta", "calcule 150 mais 30", "qual é a raiz de 16",
        "quanto é 2 elevado a 10",
    ],
    "sys_clima": [
        "como está o tempo", "qual é o clima hoje", "vai chover",
        "temperatura em São Paulo", "previsão do tempo", "como está o tempo aí fora",
        "meteorologia de hoje",
    ],
    "sys_volume_set": [
        "coloca o volume em 50", "ajusta o volume para 80",
        "volume a 30 por cento", "bota o volume em 60",
        "muda o volume para 40",
    ],
    "sys_desligar": [
        "desliga o computador", "desligue o PC", "shutdown",
        "encerra o sistema", "desliga a máquina",
    ],
    "sys_bloquear": [
        "bloqueia a tela", "trava o computador", "lock screen",
        "bloquear sessão", "travar o PC",
    ],
    "sys_abrir_app": [
        "abre o chrome", "abre o spotify", "abre o bloco de notas",
        "inicia o discord", "lança o firefox", "abrir o VS Code",
        "abre a calculadora", "inicia o WhatsApp",
    ],
    "sys_timer": [
        "cria um timer de 5 minutos", "seta um timer de 30 segundos",
        "timer de 10 minutos", "inicia um cronômetro", "conta 2 minutos",
    ],

    # Mensagens
    "msg_enviar": [
        "manda uma mensagem para o João", "envia um WhatsApp para a Maria",
        "manda um zap", "envia mensagem no instagram", "manda um dm",
    ],
    "msg_ler": [
        "tem mensagem nova", "lê minhas mensagens", "o que disseram no WhatsApp",
        "tem alguma notificação", "leia as minhas msgs",
    ],

    # Modo Jogo
    "sys_game_mode_on": [
        "ativa modo jogo", "ativa o modo jogo", "ativa game mode", "enable game mode",
        "liga modo jogo", "entra em modo jogo", "modo gamer on", "modo gaming ativar",
        "quero jogar", "libera vram pra jogar", "vai ter gaming", "modo jogo on",
        "modo de jogo", "ativar modo de jogo", "ativa modo de jogo",
        "liga o modo de jogo", "ativar modo jogo", "ativa o modo de jogo",
        "modo jogo", "ativa modo gamer", "ativar game mode",
    ],
    "sys_game_mode_off": [
        "desativa modo jogo", "desativa o modo jogo", "desativa game mode", "disable game mode",
        "sai do modo jogo", "desliga modo jogo", "modo jogo off", "volta ao normal",
        "terminei de jogar", "saindo do modo gaming", "modo gaming desativar",
        "desativar modo de jogo", "desativa modo de jogo", "sai do modo de jogo",
        "desliga o modo de jogo",
    ],

    # Modo Desenvolvedor (Dev Mode)
    "sys_dev_mode_on": [
        "ativa modo dev", "ativa o modo desenvolvedor", "ativa dev mode", "enable dev mode",
        "liga modo dev", "entra em modo desenvolvedor", "modo dev on", "modo desenvolvimento ativar",
        "inicia modo dev", "conecta ao vscode",
    ],
    "sys_dev_mode_off": [
        "desativa modo dev", "desativa o modo desenvolvedor", "desativa dev mode",
        "sai do modo dev", "desliga modo desenvolvedor", "modo dev off",
        "desconecta do vscode", "para o modo dev",
    ],
    "sys_dev_feature": [
        "implementa uma funcionalidade de login", "cria um módulo de autenticação",
        "desenvolve um sistema de cache", "adiciona feature de notificações",
        "monta um componente de dashboard", "implementa a feature de exportação",
        "cria funcionalidade de busca avançada", "desenvolve módulo de relatórios",
        "adiciona sistema de permissões", "implementa um endpoint de API",
        "cria uma funcionalidade de upload", "desenvolve o sistema de logs",
    ],
    "sys_dev_refactor": [
        "refatora o módulo de autenticação", "melhora o código do serviço de email",
        "limpa o código do controller", "reorganiza a estrutura do projeto",
        "refatora a classe de conexão", "refactora o sistema de rotas",
        "melhora o código da camada de dados", "reorganiza os imports do módulo",
    ],
    "sys_dev_debug": [
        "debuga o erro de conexão", "corrige o bug do login",
        "investiga o erro 500 na API", "debugar o problema de memória",
        "corrige o bug de renderização", "investiga o problema de performance",
        "debugar o erro de validação", "fixa o bug do websocket",
    ],
    "sys_dev_test": [
        "gera testes para o módulo de autenticação", "cria testes unitários para o serviço",
        "escreve testes para a API de usuários", "gera testes do controller de pedidos",
        "cria os testes para o módulo de pagamento", "escreve testes de integração",
        "gera testes para o componente de formulário", "cria testes para as rotas",
    ],
    "sys_dev_explain": [
        "explica o código do módulo de autenticação", "como funciona o código do router",
        "explica o código de conexão com banco", "como funciona o módulo de cache",
        "explica o arquivo de configuração", "como funciona o sistema de middleware",
        "explica o código do serviço de email", "como funciona o módulo de logs",
    ],

    # Pesquisa e conteúdo
    "pesquisar": [
        "pesquisa sobre inteligência artificial", "busca no google por Python",
        "procura informações sobre machine learning", "me fala sobre fotossíntese",
        "investiga o tema de computação quântica", "pesquise sobre o Brasil",
    ],
    "resumo_yt": [
        "resume esse vídeo do youtube", "analisa esse vídeo", "me conta o que tem nesse vídeo",
        "resume o conteúdo do youtube", "traduz e resume esse vídeo",
    ],
    "noticias": [
        "quais são as notícias de hoje", "me dá as notícias", "o que aconteceu hoje",
        "notícias do dia", "últimas notícias",
    ],
    "traduzir": [
        "traduz isso para o inglês", "como se diz isso em espanhol",
        "traduza esse texto", "tradução para o francês", "translate to english",
    ],
}

# ── Estado do classificador (lazy load, thread-safe) ─────────────────────────
_lock = threading.Lock()
_classifier: "_EmbeddingClassifier | None" = None


class _EmbeddingClassifier:
    """Encapsula o modelo MiniLM-L6-v2 e os vetores de referência."""

    def __init__(self) -> None:
        import os as _os
        from sentence_transformers import SentenceTransformer  # type: ignore
        import numpy as np  # já presente no projeto

        self._np = np
        # MiniLM roda 100% LOCAL (CPU, ~90 MB RAM, ~5ms/query) — NÃO é API.
        # JARVIS_EMBED_MODEL permite trocar o modelo (caminho de ajuste/own-model:
        # ex.: um modelo destilado/fine-tunado nosso). Tenta o cache LOCAL primeiro
        # (sem rede nem warning do HF Hub); só baixa da internet no 1º uso.
        _name = (_os.environ.get("JARVIS_EMBED_MODEL")
                 or "sentence-transformers/all-MiniLM-L6-v2")
        try:
            self._model: SentenceTransformer = SentenceTransformer(
                _name, local_files_only=True)
        except Exception:
            print("[EMBED] modelo não está em cache — baixando (só na 1ª vez)…")
            self._model = SentenceTransformer(_name)

        # Pré-computa embeddings de todos os exemplos
        self._labels: list[str] = []
        all_texts: list[str] = []
        for intent, examples in _INTENT_EXAMPLES.items():
            for ex in examples:
                self._labels.append(intent)
                all_texts.append(ex)

        self._embeddings = self._model.encode(all_texts, normalize_embeddings=True)
        print(f"[EMBED] Classificador carregado — {len(all_texts)} exemplos, "
              f"{len(_INTENT_EXAMPLES)} intents")

    def classify(self, text: str) -> tuple[str, float]:
        """
        Retorna (intent, confidence) onde confidence ∈ [0, 1].
        Se nenhum exemplo ultrapassar o threshold, retorna ("", 0.0).
        """
        query_emb = self._model.encode([text], normalize_embeddings=True)
        # Cosine similarity (vetores já normalizados → produto escalar)
        scores = (self._embeddings @ query_emb.T).flatten()
        best_idx = int(self._np.argmax(scores))
        confidence = float(scores[best_idx])
        intent = self._labels[best_idx]
        print(f"[EMBED] query='{text[:60]}' → intent={intent} conf={confidence:.3f}")
        return intent, confidence


def get_classifier() -> "_EmbeddingClassifier":
    """Retorna a instância singleton do classificador (lazy load)."""
    global _classifier
    if _classifier is None:
        with _lock:
            if _classifier is None:
                _classifier = _EmbeddingClassifier()
    return _classifier


def classify(text: str) -> tuple[str, float]:
    """
    API pública conveniente.
    Retorna ("", 0.0) se sentence-transformers não estiver instalado.
    """
    try:
        return get_classifier().classify(text)
    except ImportError:
        return "", 0.0
    except Exception as e:
        print(f"[EMBED] Erro na classificação: {e}")
        return "", 0.0
