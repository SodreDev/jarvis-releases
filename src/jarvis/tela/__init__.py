"""O conteúdo que o Jarvis monta e mostra na própria janela (dono, 2026-10-29; ADR-0055).

Listas, tabelas, resumos e comparativos em HTML simples com CSS, desenhados pelo texto rico do Qt
(`QTextDocument`): **sem JavaScript** (o renderizador não tem motor de script), **sem rede** (o
sanitizador tira imagem, link e `url()`, e a fronteira da janela confere de novo, por outra regra)
e **sem formulário**. Três peças, todas puras e testáveis sem janela:

- `sanitizar` — a allowlist de tags, atributos e propriedades CSS do subconjunto do Qt; o resto sai,
  e o texto é reescrito com escape;
- `guia` — o guia curto de design que vai ao modelo **só** no turno que monta ou muda a tela;
- `porta` — as exibições abertas, que as ferramentas `tela.*` mostram, leem e fecham pela janela.
"""

from jarvis.tela.porta import Exibicao, PortaDaTela, TelaIndisponivel
from jarvis.tela.sanitizar import HtmlSeguro, sanitizar

__all__ = ["Exibicao", "HtmlSeguro", "PortaDaTela", "TelaIndisponivel", "sanitizar"]
