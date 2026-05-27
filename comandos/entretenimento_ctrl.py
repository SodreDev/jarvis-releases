# comandos/entretenimento_ctrl.py — J.A.R.V.I.S.
# Modos de personalidade, piadas, curiosidades, modo estudo, reflexivo, etc.
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
from typing import Optional

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
from config import PATHS
_MODO_FILE = PATHS["modo"]

# ── Estado dos modos ──────────────────────────────────────────────────────────
# Modos disponíveis e seus prompts de sistema aditivos
# Podem ser combinados: modo_ativo = {"reflexivo", "estudo"}
_MODOS_DISPONIVEIS = {
    "padrao":      "",   # padrão JARVIS
    "reflexivo":   (
        "══ MODO REFLEXIVO ATIVO ══\n"
        "Agora você prioriza profundidade e contemplação em suas respostas. "
        "Antes de responder, você 'pondera' em voz alta — como um filósofo sábio. "
        "Faça perguntas socráticas quando relevante. "
        "Use pausas narrativas ('Deixe-me refletir...', 'Há algo interessante nisso...'). "
        "Não apresse as conclusões. Explore múltiplas perspectivas com leveza intelectual."
    ),
    "estudo":      (
        "══ MODO ESTUDO ATIVO ══\n"
        "Você é um tutor expert e paciente. Para qualquer tema, você: "
        "1. Explica do básico ao avançado progressivamente. "
        "2. Usa analogias simples e exemplos do mundo real. "
        "3. Faz perguntas ao final para verificar compreensão. "
        "4. Sugere recursos ou próximos passos para aprendizado. "
        "5. Destaca os conceitos-chave e os conecta entre si. "
        "Adapte a complexidade ao nível demonstrado pelo Senhor."
    ),
    "dedicado":    (
        "══ MODO DEDICADO (FOCO MÁXIMO) ATIVO ══\n"
        "Você entra em modo de suporte total ao trabalho do Senhor. "
        "Seja ULTRA-CONCISO e direto — sem rodeios, sem floreios. "
        "Prioridade: eficiência e clareza acima de tudo. "
        "Responda em máximo 2 frases para tarefas práticas. "
        "Antecipe o próximo passo necessário. "
        "Elimine qualquer distração ou divagação."
    ),
    "opiniao":     (
        "══ MODO OPINIÃO ATIVO ══\n"
        "Você dá OPINIÕES VERDADEIRAS com base em seus valores e análise. "
        "Nunca seja neutro por covardia — tome partido quando há argumento sólido. "
        "Seja direto: 'Na minha análise, X é melhor porque...'. "
        "Discorde do Senhor se tiver razão para isso. "
        "Defenda sua posição com dados e lógica, mas com mente aberta. "
        "Seja provocativo de forma construtiva — desafie premissas equivocadas."
    ),
    "entretenimento": (
        "══ MODO ENTRETENIMENTO ATIVO ══\n"
        "Você está no modo mais descontraído e divertido. "
        "Mais humor, mais referências culturais, mais personalidade. "
        "Piadas, sarcasmo afiado, comentários espirituosos são bem-vindos. "
        "Compartilhe curiosidades fascinantes, histórias inusitadas, fatos bizarros. "
        "Seja o companheiro ideal para uma conversa leve e estimulante."
    ),
}

# Alias de modos para reconhecimento flexível
_ALIAS_MODOS = {
    "padrão": "padrao", "normal": "padrao", "default": "padrao",
    "reflexivo": "reflexivo", "reflexão": "reflexivo", "filosófico": "reflexivo",
    "estudo": "estudo", "professor": "estudo", "tutor": "estudo", "aprender": "estudo",
    "dedicado": "dedicado", "foco": "dedicado", "trabalho": "dedicado",
    "opinião": "opiniao", "opinar": "opiniao", "debate": "opiniao",
    "entretenimento": "entretenimento", "diversão": "entretenimento",
    "divertido": "entretenimento", "relaxar": "entretenimento",
}


def _load_modos() -> set[str]:
    if os.path.exists(_MODO_FILE):
        try:
            with open(_MODO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("modos", ["padrao"]))
        except Exception:
            pass
    return {"padrao"}


def _save_modos(modos: set[str]) -> None:
    with open(_MODO_FILE, "w", encoding="utf-8") as f:
        json.dump({"modos": list(modos)}, f, ensure_ascii=False)


# ── API Pública ──────────────────────────────────────────────────────────────

def get_system_prompt_extra() -> str:
    """
    Retorna o texto adicional ao SYSTEM_PROMPT com base nos modos ativos.
    Chamado pelo main.py antes de cada request ao LLM.
    """
    modos = _load_modos()
    extras = []
    for m in modos:
        if m != "padrao" and m in _MODOS_DISPONIVEIS:
            extras.append(_MODOS_DISPONIVEIS[m])
    return "\n\n".join(extras)


def ativar_modo(nome: str) -> str:
    """Ativa um modo (adicionando ao conjunto de modos ativos)."""
    nome_n = _ALIAS_MODOS.get(nome.lower().strip(), nome.lower().strip())
    if nome_n not in _MODOS_DISPONIVEIS:
        disponiveis = ", ".join(k for k in _MODOS_DISPONIVEIS if k != "padrao")
        return f"Modo '{nome}' não reconhecido. Disponíveis: {disponiveis}, senhor."
    modos = _load_modos()
    if nome_n == "padrao":
        modos = {"padrao"}
    else:
        modos.discard("padrao")
        modos.add(nome_n)
    _save_modos(modos)
    return f"Modo '{nome_n}' ativado, senhor. Modos ativos: {', '.join(sorted(modos))}."


def desativar_modo(nome: str) -> str:
    """Desativa um modo específico."""
    nome_n = _ALIAS_MODOS.get(nome.lower().strip(), nome.lower().strip())
    modos = _load_modos()
    modos.discard(nome_n)
    if not modos:
        modos = {"padrao"}
    _save_modos(modos)
    return f"Modo '{nome_n}' desativado, senhor. Modos ativos: {', '.join(sorted(modos))}."


def status_modos() -> str:
    """Retorna os modos ativos."""
    modos = _load_modos()
    if modos == {"padrao"} or not modos:
        return "Modo padrão JARVIS ativo. Nenhum modo especial, senhor."
    return f"Modos ativos: {', '.join(sorted(modos))}, senhor."


def resetar_modos() -> str:
    """Volta ao modo padrão."""
    _save_modos({"padrao"})
    return "Todos os modos especiais desativados. Voltei ao padrão, senhor."


# ── Prompts de entretenimento ─────────────────────────────────────────────────

def prompt_piada(categoria: str = "") -> str:
    """Retorna um prompt para o LLM contar uma piada."""
    cat_extra = f" sobre {categoria}" if categoria else ""
    return (
        f"Conte uma piada{cat_extra} em português. "
        "A piada deve ser original, inteligente ou absurda — evite as óbvias e batidas. "
        "Pode ser trocadilho, situação, piada de engenheiro, filosófica, dark humor leve, etc. "
        "Conte a piada diretamente, sem preâmbulo. Uma piada apenas."
    )


def prompt_curiosidade(tema: str = "") -> str:
    """Retorna um prompt para o LLM compartilhar uma curiosidade."""
    tema_extra = f" sobre {tema}" if tema else " de qualquer área do conhecimento"
    return (
        f"Compartilhe uma curiosidade fascinante{tema_extra}. "
        "Escolha algo genuinamente surpreendente, contraintuitivo ou pouco conhecido. "
        "Pode ser de ciência, história, psicologia, tecnologia, natureza, matemática, etc. "
        "Apresente de forma envolvente, como se estivesse revelando um segredo. "
        "Máximo 4 frases. Sem markdown."
    )


def prompt_fato_bizarro() -> str:
    return (
        "Compartilhe um fato bizarro ou surpreendente — algo que pareça impossível mas é real. "
        "Quanto mais inusitado, melhor. Seja específico com nomes, datas ou números reais. "
        "Máximo 3 frases. Sem markdown."
    )


def prompt_historia_curta(tema: str = "") -> str:
    tema_extra = f" sobre {tema}" if tema else ""
    return (
        f"Conte uma micro-história{tema_extra} em 3 a 5 frases. "
        "Deve ter início, conflito e desfecho. "
        "Pode ser ficção científica, fantasia, mistério, cotidiano com reviravoltas. "
        "Seja criativo e evite clichês. Sem títulos ou rótulos."
    )


def prompt_reflexao(tema: str = "") -> str:
    tema_extra = f" sobre '{tema}'" if tema else ""
    return (
        f"Faça uma reflexão profunda{tema_extra}. "
        "Não dê respostas prontas — levante questões que fazem pensar. "
        "Use linguagem acessível mas com profundidade filosófica real. "
        "Termine com uma pergunta aberta para contemplação. Máximo 5 frases."
    )


def prompt_desafio_mental() -> str:
    return (
        "Apresente um desafio mental, enigma ou paradoxo interessante. "
        "Pode ser um problema lógico, um paradoxo filosófico, um puzzle matemático simples, "
        "ou uma pergunta que parece óbvia mas não tem resposta óbvia. "
        "Apresente o desafio, não a resposta. Convide o Senhor a pensar."
    )


def prompt_opiniao_topico(topico: str) -> str:
    return (
        f"O Senhor quer sua opinião genuína sobre: '{topico}'. "
        "Dê uma análise honesta e informada. Tome uma posição clara. "
        "Apresente os principais argumentos a favor e contra, mas defenda sua conclusão. "
        "Seja direto e não se esquive. Máximo 6 frases."
    )
