// vscode_extension/jarvis-dev-bridge/src/extension.ts
// Ponto de entrada da extensão VSCode — conecta ao Jarvis Dev Mode via WebSocket
// e encaminha prompts estruturados ao GitHub Copilot Chat.

import * as vscode from "vscode";
import { JarvisBridge, JarvisMessage } from "./bridge";

let bridge: JarvisBridge | null = null;
let statusBarItem: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;

// ── Activation ───────────────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext): void {
    outputChannel = vscode.window.createOutputChannel("Jarvis Dev Bridge");
    log("Extensão Jarvis Dev Bridge ativada.");

    // Status bar (canto inferior esquerdo)
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
    statusBarItem.command = "jarvis.devBridge.status";
    updateStatusBar(false);
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // Registra comandos
    context.subscriptions.push(
        vscode.commands.registerCommand("jarvis.devBridge.connect", cmdConnect),
        vscode.commands.registerCommand("jarvis.devBridge.disconnect", cmdDisconnect),
        vscode.commands.registerCommand("jarvis.devBridge.status", cmdStatus)
    );

    // Auto-connect se configurado
    const config = vscode.workspace.getConfiguration("jarvis.devBridge");
    if (config.get<boolean>("autoConnect", false)) {
        cmdConnect();
    }
}

export function deactivate(): void {
    bridge?.disconnect();
    bridge = null;
}

// ── Comandos ─────────────────────────────────────────────────────────────────

function cmdConnect(): void {
    if (bridge?.connected) {
        vscode.window.showInformationMessage("Jarvis Dev Bridge: já conectado.");
        return;
    }

    const config = vscode.workspace.getConfiguration("jarvis.devBridge");
    const host = config.get<string>("host", "127.0.0.1");
    const port = config.get<number>("port", 6589);
    const reconnectInterval = config.get<number>("reconnectInterval", 5000);

    // Cria nova instância se necessário
    if (bridge) {
        bridge.disconnect();
    }
    bridge = new JarvisBridge({ host, port, reconnectInterval });

    bridge.on("connected", () => {
        log(`Conectado ao Jarvis em ws://${host}:${port}`);
        updateStatusBar(true);
        vscode.window.showInformationMessage("Jarvis Dev Bridge: conectado!");
    });

    bridge.on("disconnected", () => {
        log("Desconectado do Jarvis.");
        updateStatusBar(false);
    });

    bridge.on("error", (err: Error) => {
        log(`Erro de conexão: ${err.message}`);
    });

    bridge.on("prompt", (msg: JarvisMessage) => {
        handlePrompt(msg);
    });

    bridge.connect();
    log(`Tentando conectar ao Jarvis em ws://${host}:${port}...`);
}

function cmdDisconnect(): void {
    if (!bridge) {
        vscode.window.showInformationMessage("Jarvis Dev Bridge: não está conectado.");
        return;
    }
    bridge.disconnect();
    bridge = null;
    updateStatusBar(false);
    vscode.window.showInformationMessage("Jarvis Dev Bridge: desconectado.");
}

function cmdStatus(): void {
    const connected = bridge?.connected ?? false;
    const status = connected ? "🟢 Conectado" : "🔴 Desconectado";
    vscode.window.showInformationMessage(`Jarvis Dev Bridge: ${status}`);
}

// ── Handler de prompts ───────────────────────────────────────────────────────

async function handlePrompt(msg: JarvisMessage): Promise<void> {
    const promptId = msg.id ?? "unknown";
    const prompt = msg.prompt ?? "";
    const intent = msg.intent ?? "feature_request";

    log(`Prompt recebido [${promptId.substring(0, 8)}…] intent=${intent} (${prompt.length} chars)`);

    // Envia ack "received"
    bridge?.sendAck({ type: "ack", id: promptId, status: "received" });

    if (!prompt) {
        bridge?.sendAck({ type: "ack", id: promptId, status: "error", message: "Prompt vazio" });
        return;
    }

    try {
        // Envia ack "executing"
        bridge?.sendAck({ type: "ack", id: promptId, status: "executing", message: "Abrindo Copilot Chat" });

        // Estratégia 1: Tenta enviar via vscode.chat.sendRequest (VSCode 1.93+)
        const sent = await sendToCopilotChat(prompt);

        if (sent) {
            bridge?.sendAck({ type: "ack", id: promptId, status: "done", message: "Prompt enviado ao Copilot" });
            log(`Prompt [${promptId.substring(0, 8)}…] entregue ao Copilot Chat.`);
        } else {
            // Estratégia 2: Fallback — copia para clipboard + abre Copilot Chat
            await fallbackClipboard(prompt);
            bridge?.sendAck({
                type: "ack",
                id: promptId,
                status: "done",
                message: "Prompt copiado para clipboard. Cole no Copilot Chat."
            });
            log(`Prompt [${promptId.substring(0, 8)}…] copiado para clipboard (fallback).`);
        }
    } catch (err) {
        const errorMsg = err instanceof Error ? err.message : String(err);
        bridge?.sendAck({ type: "ack", id: promptId, status: "error", message: errorMsg });
        log(`Erro ao processar prompt: ${errorMsg}`);
    }
}

/**
 * Tenta enviar o prompt diretamente ao Copilot Chat via API interna do VSCode.
 * Retorna true se conseguiu, false se o comando não está disponível.
 */
async function sendToCopilotChat(prompt: string): Promise<boolean> {
    try {
        // Tenta abrir o painel de chat do Copilot e enviar o prompt
        // O comando varia conforme a versão do VSCode / Copilot:
        //   - "workbench.action.chat.open" abre o painel
        //   - Inserir texto no chat

        // Abrir o Copilot Chat
        await vscode.commands.executeCommand("workbench.action.chat.open");

        // Pequena pausa para o painel abrir
        await sleep(500);

        // Tenta enviar o prompt usando a API de chat
        // Método 1: workbench.action.chat.sendToNewChat (VSCode recente)
        try {
            await vscode.commands.executeCommand(
                "workbench.action.chat.sendToNewChat",
                { inputValue: prompt }
            );
            return true;
        } catch {
            // Método 1 não disponível
        }

        // Método 2: Insere via clipboard + paste no editor de chat ativo
        // Este é o fallback mais confiável
        return false;

    } catch {
        return false;
    }
}

/**
 * Fallback: copia o prompt para o clipboard e abre o Copilot Chat.
 * O usuário cola manualmente (Ctrl+V) no painel.
 */
async function fallbackClipboard(prompt: string): Promise<void> {
    await vscode.env.clipboard.writeText(prompt);
    await vscode.commands.executeCommand("workbench.action.chat.open");
    vscode.window.showInformationMessage(
        "Prompt Jarvis copiado para o clipboard. Cole (Ctrl+V) no Copilot Chat."
    );
}

// ── Utilitários ──────────────────────────────────────────────────────────────

function updateStatusBar(connected: boolean): void {
    if (connected) {
        statusBarItem.text = "$(plug) Jarvis Dev";
        statusBarItem.tooltip = "Jarvis Dev Bridge: Conectado";
        statusBarItem.backgroundColor = undefined;
    } else {
        statusBarItem.text = "$(debug-disconnect) Jarvis Dev";
        statusBarItem.tooltip = "Jarvis Dev Bridge: Desconectado — clique para ver status";
        statusBarItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    }
}

function log(message: string): void {
    const timestamp = new Date().toLocaleTimeString();
    outputChannel.appendLine(`[${timestamp}] ${message}`);
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
