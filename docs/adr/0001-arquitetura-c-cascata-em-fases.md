# ADR-0001 — Arquitetura C: cascata streaming local controlável, S2S como experimento

**Data:** 2026-10-15 · **Estado:** aceita (decisão do dono) · **Decide:** dono

## Contexto
Três caminhos foram pesquisados (relatório `pesquisa/01-tempo-real.md`, 2026-10-15):
- **A — cascata local:** AEC → VAD/detector de turno → ASR parcial → LLM → TTS. Pontos de controle, log e componente trocável; perde sinais paralinguísticos e acumula erro.
- **B — API speech-to-speech** (OpenAI Realtime, Gemini Live) ou modelo nativo full-duplex (Moshi, ~200 ms práticos relatados no artigo): mais natural, mas turn-taking e raciocínio ficam em grande parte caixa-preta e dependentes do fornecedor.
- **C — híbrida em fases:** começa por A e desenha o barramento de modo que B entre depois como adaptador de diálogo, preservando AEC, event log, epoch, PDP e executor do lado de cá.

O Jarvis vai mexer em arquivos, janelas, calendário e automações. Auditabilidade e cancelamento valem mais que naturalidade no início. Referência honesta de latência de cascata: Voice-Light mediu mediana de 758 ms do endpoint VAD ao primeiro áudio em 36 turnos (estudo de caso pequeno, inglês).

## Decisão
Adotar **C**: cascata streaming local controlável com S1/S2, epoch e cancelamento por barge-in nas fases F0–F4. API speech-to-speech ou Moshi só em F5, como experimento comparado no mesmo corpus, nunca como dependência.

## Alternativas descartadas
- **B direto:** entrega naturalidade antes de entregar controle; o dono perderia a capacidade de auditar por que o assistente agiu.
- **Treinar um Moshi próprio:** fora do orçamento e não resolve ferramentas, memória, AEC nem autorização.

## Consequências
- O barramento (§3 da SPEC) precisa ser adaptador-agnóstico desde F0, senão F5 não acontece.
- SLO-5 (600–900 ms) é a meta realista; prometer 200 ms seria copiar número de outra arquitetura.
- Toda melhoria de naturalidade compete com auditabilidade e precisa de número para entrar.

## Como invalidar
F5 mostrar, no mesmo corpus de F1, que o S2S reduz falso corte **e** atraso sem piorar auditabilidade, custo, pt-BR e segurança. Aí o talker troca; o núcleo (epoch, PDP, executor, memória) permanece.
