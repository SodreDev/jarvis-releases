# Corpus sintético de endereçamento (ADR-0029)

Falas em português do Brasil escritas à mão, **sem dado real do dono**, para medir se o detector
de endereçamento separa "é com o Jarvis" de "não é". Cada linha de `falas.jsonl`:

- `rotulo`: `jarvis` (a pessoa fala com o assistente) ou `outro` (sozinha, com outra pessoa,
  TV, comentário);
- `intencao`: `resposta`, `sugestao`, `acao` ou `ignorar` (a que o detector deve devolver);
- `jarvis_perguntou`: o assistente acabou de fazer uma pergunta (sinal local do detector).

Há casos **difíceis de propósito**: ordem dada a outra pessoa ("pode abrir a janela, por favor?"),
o nome do assistente citado em terceira pessoa ("o Jarvis é bem rápido, né?"), respostas curtas
("sim") que só valem depois de uma pergunta dele, e perguntas feitas a outro ouvinte.

É amostra pequena (58 falas): serve para comparar abordagens e achar falha grosseira, **não** para
fixar limiar de produto — o ADR-0029 pede 200–500 por cenário antes disso. Medir:
`uv run python tools/medir_enderecamento.py --regras` (local) ou `--openrouter` (nuvem; gasta
uma chamada por fala, ~US$ 0,00002 cada).
