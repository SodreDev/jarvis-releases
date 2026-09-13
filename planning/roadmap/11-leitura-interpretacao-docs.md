# Plano 11 — Leitura & Interpretação de Documentos

> Complementar ao plano 10 (geração). Aqui: o JARVIS LÊ e ENTENDE documentos existentes para resumir, reestruturar, gerar versões novas.

## Estado Atual

- [comandos/pdf_ctrl.py](../../comandos/pdf_ctrl.py) — extrai texto de PDF (PyMuPDF), fuzzy search em Downloads.
- Sem OCR.
- Sem leitura de DOCX/XLSX/PPTX.
- Sem extração de imagens.
- Sem análise estrutural (qual é título, qual é tabela, qual é figura).

## Plano

### Pipelines por formato

```
documents/readers/
├── pdf.py        ← PyMuPDF (texto + imagens) + OCR fallback
├── docx.py       ← python-docx + análise de styles
├── pptx.py       ← python-pptx + extração de slides
├── xlsx.py       ← openpyxl + detecção de tabelas
├── markdown.py
├── html.py       ← BeautifulSoup + readability-lxml
└── image.py      ← OCR direto via pytesseract / EasyOCR
```

### Modelo interno — DocumentTree

```python
@dataclass
class DocumentNode:
    kind: Literal["heading", "paragraph", "list", "table", "image", "code", "quote"]
    level: int                  # h1=1, h2=2…
    content: str | bytes
    metadata: dict              # page, position, style
    children: list["DocumentNode"]

@dataclass
class Document:
    source: Path
    format: str
    title: str | None
    nodes: list[DocumentNode]
    images: list[ExtractedImage]
    tables: list[ExtractedTable]
    metadata: dict              # author, created, pages, lang
```

Cada reader retorna `Document` — pipeline a jusante (resumo, reestruturação, embeddings) opera no modelo interno, agnóstico de formato.

### OCR

- Default: **`pytesseract`** (Tesseract instalado pelo instalador).
- Opcional via toggle: **`EasyOCR`** (melhor multilíngue) ou Vision LLM (Qwen3-VL já temos).
- Detecção: se PDF tem <X chars por página → roda OCR; caso contrário usa texto nativo.

### Análise estrutural

- Heurísticas de heading: fonte maior, bold, posição.
- Detecção de tabela em PDF: `pdfplumber` complementar a PyMuPDF.
- Detecção de figura: bounding box + alt-text quando existir.

### Embeddings de documento (opt-in)

- Cada `DocumentNode` vira chunk de 200-500 tokens.
- Embedding via Tier 2 do plano 07 (memória).
- Permite "JARVIS, lembra do que aquela apostila falou sobre X?" → busca semântica.

### Casos de uso

1. **Resumir PDF** (já temos parcial): expandir com seção-por-seção, não só texto raso.
2. **Reorganizar**: "transforma esse PDF em apresentação" → `Document` → `documents/generators/pptx.py`.
3. **Extrair tabela**: "exporta a tabela 3 desse PDF para Excel".
4. **Comparar documentos**: diff semântico.
5. **Resposta a pergunta sobre PDF**: RAG sobre os chunks.

### Pipeline LLM

- Para resumir/reorganizar: chunk-by-chunk com **map-reduce**:
  - Map: resumo de cada chunk.
  - Reduce: síntese consolidando.
- Limites: contexto do modelo principal (`llama-3.3-70b-versatile` 128k) é generoso, então maioria dos docs cabe em 1 call.

## Decisões pendentes

1. **Tesseract dependency no instalador**: bundle vs download on-demand? Recomendação: detectar instalação; oferecer download se ausente; OCR só ativo se presente.
2. **Idiomas OCR padrão**: `por+eng`. Adicionais via toggle.
3. **PDFs escaneados pesados**: rodar em thread baixa prioridade + cache de OCR em `data/ocr_cache/`.

## Riscos

- OCR é lento (1-3s/página). UX: indicador de progresso + cache.
- PDFs malformados quebram parsers. Try/except por página, não pelo doc inteiro.

## Referências de código

- [comandos/pdf_ctrl.py](../../comandos/pdf_ctrl.py)
- [comandos/ocr_ctrl.py](../../comandos/ocr_ctrl.py)

## Histórico

- 2026-05-25 — Plano criado.
