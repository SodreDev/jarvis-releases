# Corpus do Jarvis — uma página

Aqui ficam os dados que medem o projeto. **Nada de código** e **nada de segredo**: o corpus é
material de avaliação, versionado com cuidado e com consentimento explícito de quem aparece
nele.

Quem grava o conteúdo é o **dono** (e o orquestrador, quando ele pedir). Este diretório traz a
estrutura, o formato e as regras — foi o cartão F0-08 que as criou.

## O que vai em cada pasta

| pasta | o que é | quem usa | quando |
|---|---|---|---|
| `turnos/` | áudio de pausa real em pt-BR, com rótulo de fim de turno | detector semântico de turno, SLO-4 e SLO-9 | F1 |
| `consultas/` | perguntas anotadas com a resposta certa e os negativos (C2) | medição de recuperação da §8.1/§8.2 | F3 |
| `cenarios/` | diálogos de cenário com a decisão esperada do PDP | suíte de política e de prompt injection | F2/F4 |
| `exportado/` | C1: memórias do Orchestrator no esquema da §6.2 (gerado, **não** versionado) | dimensionar o grafo (F0-05) e calibrar | F0 |

Cada pasta tem um `README.md` com o formato exato e um exemplo. O formato é sempre **JSONL**
(uma linha por item), porque é o que dá para revisar em diff e juntar sem conflito.

## Regras que valem para todo o corpus

1. **Consentimento primeiro.** Voz, nome ou conversa de outra pessoa só entra com o termo de
   `CONSENTIMENTO.md` assinado, e com o identificador do termo na linha do item.
2. **Segredo nunca entra.** Chave, token, senha, caminho de cofre, conteúdo de `.env`: não se
   redige depois, não se grava antes. O exportador de C1 redige o que encontra e **falha** se
   achar algo que não sabe redigir.
3. **Áudio separado do rótulo.** O `.wav` fica em `turnos/audio/` e o rótulo em
   `turnos/rotulos.jsonl`, apontando o arquivo pelo nome e pelo sha256.
4. **Hash de tudo.** `corpus/manifesto.json` guarda o sha256 de cada arquivo. Mudou um byte, o
   `tools/corpus.py verificar` acusa — é assim que medição feita hoje continua comparável
   amanhã.
5. **70/30.** Calibração usa 70% e os números publicados saem dos 30% retidos (§6.8). A divisão
   fica no próprio item (`"split": "calibracao" | "retido"`), decidida quando o item entra, não
   na hora de medir.
6. **Sem dado de produção de terceiro.** Nada de e-mail de cliente, documento de empresa ou
   captura de tela com informação de outra pessoa.

## Comandos

```bash
uv run --frozen python tools/corpus.py manifesto    # (re)gera corpus/manifesto.json
uv run --frozen python tools/corpus.py verificar    # falha se algum arquivo mudou
uv run --frozen python tools/corpus.py resumo       # conta itens por pasta

# C1: exporta as memórias do Orchestrator para o esquema da §6.2
uv run --frozen python tools/exportar_orchestrator.py --dump dump.txt --saida corpus/exportado/c1.sqlite
```
