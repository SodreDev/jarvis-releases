# ADR-0012 — Licenças verificadas na origem: emenda à ADR-0011 (bge é Apache-2.0, XTTS-v2 está fora)

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor (verificação), confirma a ADR-0011 do dono
**Emenda:** ADR-0011 (reranker de licença comercial), itens 1 e 2.
**Commit da verificação:** `2658c29` · **`n` = 13 modelos** conferidos na origem · **hardware:**
irrelevante para esta ADR (a verificação é de metadado de licença, não de desempenho).

## Contexto

A ADR-0011 fechou que licença é requisito de produto e deixou uma pendência explícita: os
model cards oficiais precisavam ser verificados na F0-09, porque as licenças citadas vinham de
agregadores e **uma fonte divergiu** (dizia MIT para o `bge-reranker-v2-m3`).

A verificação foi feita em 2026-10-15 contra a origem — API do model card do Hugging Face e
API de licença do GitHub, nunca agregador — para os treze modelos do registro
`licenses/modelos.toml`. Tabela comitada em `docs/licencas.md`, com revisão do repositório do
modelo e data de acesso; o script é `tools/license_gate.py --online`.

Dois achados mudam o que estava escrito:

1. **A divergência era de identificação, não de licença.** O model card oficial de
   `BAAI/bge-reranker-v2-m3` diz `apache-2.0` (revisão `953dc6f6f85a`). O MIT que o agregador
   mostrava é do `BAAI/bge-m3`, que é **embedding**, não reranker, e é MIT mesmo (revisão
   `5617a9f61b02`). Nenhum dos seis candidatos nomeados na ADR-0011 é não comercial, então a
   ordem de preferência para medir em F3 segue **sem mudança**.
2. **Achado novo, fora da lista original: `coqui/XTTS-v2` é não comercial.** O Hugging Face
   mostra `license: other`, e o `license_name` é `coqui-public-model-license`
   (<https://coqui.ai/cpml>), que permite apenas uso não comercial. Como TTS é escolha da F1,
   o modelo entra agora no registro como `barrado`, antes de alguém considerá-lo.
   No mesmo passo apareceu uma obrigação que não é bloqueio:
   `nvidia/parakeet-tdt-0.6b-v2` é **CC-BY-4.0** — uso comercial permitido **com atribuição
   visível no produto**.

## Decisão

A porta de licença bloqueia não comercial e desconhecido-em-uso, **avisa** em atribuição
obrigatória e em copyleft forte, e a tabela `licença × modelo × fonte` fica comitada e
verificada pelo CI; `coqui/XTTS-v2` está barrado desde já, e `parakeet-tdt-0.6b-v2` só pode
entrar com a atribuição aparecendo no produto.

## Alternativas descartadas

- **Consultar os model cards no CI** (em vez de usar a tabela comitada): porta de qualidade que
  depende de rede falha pelo motivo errado, e cai quando o Hugging Face cai. A verificação na
  origem é manual, datada e reproduzível por `--online`.
- **Tratar `license: other` como "a verificar depois"**: foi exatamente o caso do XTTS-v2, cujo
  nome de licença só aparece em `license_name`. `other` passa a ser **desconhecida**, que
  bloqueia quando o item está em uso.
- **Bloquear copyleft forte junto com NC**: GPL/AGPL permitem uso comercial; o que elas
  obrigam é abrir o derivado. Vira aviso, e bloqueio só com `--estrito-copyleft`.

## Consequências

- Mais fácil: a ordem de preferência da ADR-0011 para F3 está confirmada por fonte oficial,
  com revisão e data, e não precisa ser revisitada.
- Mais caro: TTS da F1 perde um candidato popular (XTTS-v2) e ganha a necessidade de verificar
  **voz por voz** no `rhasspy/piper-voices`, onde algumas vozes são CC-BY-SA mesmo com o
  repositório em MIT.
- Passa a ser obrigatório testar: a porta falha em NC injetado (modelo e dependência), e a
  tabela comitada não pode divergir do registro — o CI verifica as duas coisas.
- Passa a ser obrigatório no produto: se `parakeet` for escolhido, a atribuição CC-BY aparece
  na interface; a porta avisa em todo commit para isso não sumir.

## Como invalidar esta decisão

Um model card mudar de licença (a revisão comitada deixa isso visível em `--online`), ou a
Coqui relicenciar o XTTS-v2 em termos que permitam uso comercial.
