//! Braço Rust do harness de captura (cartão F0-04, SPEC §2 decisão D1).
//!
//! Mede o caminho `frame de 20 ms → pré-filtro → VAD barato → evento`, com a MESMA
//! aritmética do braço Python (f32, mesmos limiares, mesma histerese), para que a
//! comparação seja de linguagem e não de algoritmo.
//!
//! **Só biblioteca padrão**: compila com `rustc -O -o vad_bench vad_bench.rs`, sem cargo,
//! sem rede e sem instalar nada na máquina — foi exigência do dono.
//!
//! Uso: `vad_bench <arquivo.raw> <frames> <execucao>`; o áudio é S16LE mono 16 kHz.
//! A saída é uma linha JSON com as estatísticas, lida pelo `tools/harness_captura.py`.

use std::env;
use std::fs;
use std::time::Instant;

const TAXA: usize = 16_000;
const FRAME: usize = TAXA / 50; // 20 ms = 320 amostras
const PRE_ENFASE: f32 = 0.97;
const LIMIAR_DB: f32 = -45.0;
const LIMIAR_ZCR: f32 = 0.35;
const FRAMES_PARA_LIGAR: u32 = 2;
const FRAMES_PARA_DESLIGAR: u32 = 6;

/// Estado do detector: o que o `audio-io` carregaria entre frames.
struct Vad {
    anterior: f32,
    acima: u32,
    abaixo: u32,
    falando: bool,
}

impl Vad {
    fn novo() -> Self {
        Vad { anterior: 0.0, acima: 0, abaixo: 0, falando: false }
    }

    /// Um frame: pré-ênfase, energia RMS em dB, taxa de cruzamento por zero, histerese.
    /// Devolve `Some(true)` quando a fala começa e `Some(false)` quando termina.
    fn frame(&mut self, amostras: &[f32]) -> Option<bool> {
        let mut soma = 0.0f32;
        let mut cruzamentos = 0u32;
        let mut sinal_anterior = false;
        for (i, &x) in amostras.iter().enumerate() {
            let filtrado = x - PRE_ENFASE * self.anterior;
            self.anterior = x;
            soma += filtrado * filtrado;
            let sinal = filtrado >= 0.0;
            if i > 0 && sinal != sinal_anterior {
                cruzamentos += 1;
            }
            sinal_anterior = sinal;
        }
        let rms = (soma / amostras.len() as f32).sqrt();
        let db = 20.0 * (rms + 1e-12).log10();
        let zcr = cruzamentos as f32 / amostras.len() as f32;

        let voz = db > LIMIAR_DB && zcr < LIMIAR_ZCR;
        if voz {
            self.acima += 1;
            self.abaixo = 0;
        } else {
            self.abaixo += 1;
            self.acima = 0;
        }
        if !self.falando && self.acima >= FRAMES_PARA_LIGAR {
            self.falando = true;
            return Some(true);
        }
        if self.falando && self.abaixo >= FRAMES_PARA_DESLIGAR {
            self.falando = false;
            return Some(false);
        }
        None
    }
}

fn percentil(ordenado: &[f64], p: f64) -> f64 {
    if ordenado.is_empty() {
        return 0.0;
    }
    let pos = ((p / 100.0) * (ordenado.len() - 1) as f64).round() as usize;
    ordenado[pos.min(ordenado.len() - 1)]
}

fn main() {
    let argumentos: Vec<String> = env::args().collect();
    if argumentos.len() < 4 {
        eprintln!("uso: vad_bench <arquivo.raw> <frames> <execucao>");
        std::process::exit(2);
    }
    let caminho = &argumentos[1];
    let frames_pedidos: usize = argumentos[2].parse().expect("frames");
    let execucao: u32 = argumentos[3].parse().expect("execucao");

    let bruto = fs::read(caminho).expect("ler áudio");
    let total_amostras = bruto.len() / 2;
    let disponiveis = total_amostras / FRAME;
    let frames = frames_pedidos.min(disponiveis);

    // Converte tudo antes do laço: a medição é do processamento, não da decodificação.
    let mut amostras = vec![0.0f32; total_amostras];
    for i in 0..total_amostras {
        let bytes = [bruto[2 * i], bruto[2 * i + 1]];
        amostras[i] = i16::from_le_bytes(bytes) as f32 / 32768.0;
    }

    let mut vad = Vad::novo();
    let mut tempos = Vec::with_capacity(frames);
    let mut eventos = 0u32;
    for f in 0..frames {
        let pedaco = &amostras[f * FRAME..(f + 1) * FRAME];
        let inicio = Instant::now();
        let evento = vad.frame(pedaco);
        let gasto = inicio.elapsed().as_secs_f64() * 1000.0;
        tempos.push(gasto);
        if evento.is_some() {
            eventos += 1;
        }
    }

    let mut ordenado = tempos.clone();
    ordenado.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let soma: f64 = tempos.iter().sum();
    println!(
        "{{\"braco\":\"rust-std\",\"execucao\":{},\"n\":{},\"eventos\":{},\"media_ms\":{:.6},\
\"p50_ms\":{:.6},\"p95_ms\":{:.6},\"p99_ms\":{:.6},\"max_ms\":{:.6},\"gc_pausas\":0,\
\"gc_ms\":0.0}}",
        execucao,
        frames,
        eventos,
        soma / frames as f64,
        percentil(&ordenado, 50.0),
        percentil(&ordenado, 95.0),
        percentil(&ordenado, 99.0),
        ordenado[ordenado.len() - 1]
    );
}
