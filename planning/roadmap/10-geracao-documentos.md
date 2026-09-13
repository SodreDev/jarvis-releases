# Plano 10 — Geração de Documentos Visuais (PDF/DOCX/PPTX/XLSX/MD)

> Foco: produzir documentos **profissionais e bonitos**, não só funcionais. Hierarquia visual, espaçamento, imagens coerentes, tabelas formatadas.

## Estado Atual

- Nenhum módulo de geração de documentos.
- `comandos/pdf_ctrl.py` só LÊ PDFs (PyMuPDF) — plano 11 trata da expansão de leitura.
- `comandos/export_ctrl.py` existe — verificar escopo.

## Plano

### Arquitetura — `documents/`

```
documents/
├── generators/
│   ├── pdf.py          ← reportlab + WeasyPrint (HTML→PDF)
│   ├── docx.py         ← python-docx
│   ├── pptx.py         ← python-pptx
│   ├── xlsx.py         ← openpyxl + xlsxwriter
│   └── markdown.py
├── templates/
│   ├── pdf/
│   │   ├── executive_report.html      ← HTML+CSS template
│   │   ├── one_pager.html
│   │   └── briefing.html
│   ├── pptx/
│   │   ├── modern_dark.pptx           ← arquivo template editável
│   │   ├── classic_light.pptx
│   │   └── stark.pptx
│   ├── docx/
│   │   ├── report.docx
│   │   └── memo.docx
│   └── xlsx/
│       ├── dashboard.xlsx
│       └── budget.xlsx
├── design_system.py    ← cores, fontes, espaçamento padronizados
├── image_provider.py   ← busca/curadoria de imagens
├── chart_builder.py    ← matplotlib/plotly headless para gráficos
└── layout_engine.py    ← decide hierarquia visual (grid, espaços)
```

### Pipeline de geração

1. **Briefing**: usuário pede "monta apresentação sobre X, 10 slides".
2. **Outliner** (LLM): gera estrutura — título, seções, bullets por slide.
3. **Asset gathering**: `image_provider` busca imagens (Unsplash/Pexels API, com filtro de tema), `chart_builder` gera gráficos se houver dados.
4. **Layout engine**: aplica template + design system → decide qual slide leva imagem grande, qual leva 2 colunas, etc.
5. **Renderer**: `pptx_generator.render(spec, template="modern_dark") → arquivo .pptx`.

### Design system (`design_system.py`)

```python
PALETTES = {
    "stark":     {"primary": "#00d8ff", "accent": "#ff3860", "bg": "#0a0e1a", "text": "#e6e6e6"},
    "executive": {"primary": "#1a4d8f", "accent": "#d4a017", "bg": "#ffffff", "text": "#212121"},
    "modern":    {"primary": "#22c55e", "accent": "#a855f7", "bg": "#f9fafb", "text": "#111827"},
}
FONTS = {
    "heading": "Inter",
    "body": "Source Sans 3",
    "mono": "JetBrains Mono",
}
SPACING = {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 40}
```

### Templates por formato

#### PPTX
- Templates `.pptx` reais (não gerados do zero) — designer-friendly, editáveis no PowerPoint.
- Cada template tem **slide masters** definidos: capa, conteúdo 1-col, conteúdo 2-col, imagem-fullwidth, citação, fim.
- `python-pptx` clona layouts e popula placeholders.

#### PDF
- Geração via HTML→PDF (WeasyPrint) — HTML/CSS oferece tipografia/grid muito superior ao `reportlab` puro.
- Templates Jinja2 com CSS print-aware.
- Fallback: `reportlab` quando precisar de geração programática complexa (sem HTML).

#### DOCX
- `python-docx` com styles pré-definidos no template.
- Geração programática limitada — recomendado para relatórios estruturados, não para documentos com layout complexo.

#### XLSX
- `openpyxl` para escrita, `xlsxwriter` para charts.
- Templates com formatação condicional já configurada → JARVIS só popula dados.

### Imagens

#### Fontes (todas opt-in, default OFF)
- **Unsplash API** (gratuito com chave) — fotos de qualidade.
- **Pexels API** — alternativa.
- **DALL-E / SDXL local** — geração quando nada relevante for encontrado (opt-in pesado).
- **Cache local** em `data/image_cache/` por hash de query.

#### Curadoria
- Embedding da query + embedding da imagem (`CLIP`) → escolhe top-N.
- Filtro de aspect ratio compatível com placeholder do template.
- Filtro de "evita rosto humano genérico" e "evita stock fotos óbvias".

### Gráficos

- `matplotlib` (estilo limpo `seaborn-v0_8-darkgrid`) ou `plotly` (interativo, para painel Stark).
- Paleta vem do design system.
- Auto-detecta tipo: série temporal → linha; categórico → barra; proporções → donut/pie (com moderação).

### Layout engine

Heurísticas:
- Slide com >80 caracteres de bullet → quebrar em 2 slides.
- Slide com imagem + texto → layout 60/40.
- Capa → tipografia gigante centralizada + imagem fundo blurred.
- Slide-citação → quote em itálico + autor pequeno embaixo.

### Variantes opt-in

- **Tema configurável**: usuário escolhe paleta default (`DOC_DEFAULT_THEME=stark`).
- **Marca pessoal**: pasta `documents/brand/` com logo, paleta sobreposta — opt-in.

## Decisões pendentes

1. **Engine PDF**: WeasyPrint precisa GTK+ no Windows — pesado. Alternativa: `playwright` headless renderiza HTML → `page.pdf()` (já temos Playwright). **Recomendação: usar Playwright para PDF — zero deps extras.**
2. **Geração de imagens local**: SDXL é >5GB. Default OFF, mas suporte via toggle p/ quem tiver GPU.
3. **Templates editáveis pelo usuário**: pasta `documents/templates/user/` que sobrescreve defaults. Sim.

## Riscos

- Documentos "gerados por IA" parecem genéricos. Mitigação: templates artesanais bem feitos + variação de layouts + assets reais.
- Direitos de imagem: Unsplash/Pexels OK; nunca raspar Google Images. Documentar.
- Performance: gerar 20 slides com imagens e gráficos pode levar 30s+. Indicador de progresso.

## Referências de código

- [comandos/export_ctrl.py](../../comandos/export_ctrl.py)
- [requirements.txt](../../requirements.txt) — adicionar `python-pptx`, `python-docx`, `openpyxl`, `xlsxwriter`, `matplotlib`, `jinja2`

## Histórico

- 2026-05-25 — Plano criado.
