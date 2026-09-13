// vscode_extension/jarvis-dev-bridge/src/bridge.ts
// WebSocket client wrapper com reconexão automática e protocolo JSON.

import WebSocket from "ws";
import { EventEmitter } from "events";

/** Mensagem recebida do Jarvis. */
export interface JarvisMessage {
    type: "prompt" | "shutdown" | "pong";
    id?: string;
    prompt?: string;
    intent?: string;
    autonomous?: boolean;
    message?: string;
}

/** Mensagem de ack enviada ao Jarvis. */
export interface AckMessage {
    type: "ack";
    id: string;
    status: "received" | "executing" | "done" | "error";
    message?: string;
}

export interface BridgeOptions {
    host: string;
    port: number;
    reconnectInterval: number;
}

/**
 * WebSocket client que se conecta ao servidor Jarvis Dev Mode.
 *
 * Eventos emitidos:
 *   - "prompt"     → JarvisMessage (quando Jarvis envia um prompt)
 *   - "connected"  → void
 *   - "disconnected" → void
 *   - "error"      → Error
 */
export class JarvisBridge extends EventEmitter {
    private ws: WebSocket | null = null;
    private options: BridgeOptions;
    private shouldReconnect = false;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private _connected = false;

    constructor(options: BridgeOptions) {
        super();
        this.options = options;
    }

    /** Inicia a conexão WebSocket. */
    connect(): void {
        if (this._connected && this.ws?.readyState === WebSocket.OPEN) {
            return;
        }

        this.shouldReconnect = true;
        this.doConnect();
    }

    /** Fecha a conexão e desabilita reconexão. */
    disconnect(): void {
        this.shouldReconnect = false;
        this.clearReconnect();

        if (this.ws) {
            this.ws.removeAllListeners();
            if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
                this.ws.close(1000, "User disconnect");
            }
            this.ws = null;
        }

        if (this._connected) {
            this._connected = false;
            this.emit("disconnected");
        }
    }

    /** Envia ack ao Jarvis. */
    sendAck(ack: AckMessage): boolean {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            return false;
        }
        try {
            this.ws.send(JSON.stringify(ack));
            return true;
        } catch {
            return false;
        }
    }

    /** Retorna true se conectado. */
    get connected(): boolean {
        return this._connected && this.ws?.readyState === WebSocket.OPEN;
    }

    // ── Internals ────────────────────────────────────────────────────────

    private doConnect(): void {
        this.clearReconnect();

        const url = `ws://${this.options.host}:${this.options.port}`;
        const ws = new WebSocket(url);
        this.ws = ws;

        ws.on("open", () => {
            this._connected = true;
            this.emit("connected");
            // Envia ping inicial
            ws.send(JSON.stringify({ type: "status", message: "VSCode connected" }));
        });

        ws.on("message", (data: WebSocket.Data) => {
            try {
                const msg: JarvisMessage = JSON.parse(data.toString());
                this.handleMessage(msg);
            } catch {
                // Ignora mensagens não-JSON
            }
        });

        ws.on("close", () => {
            const wasConnected = this._connected;
            this._connected = false;
            if (wasConnected) {
                this.emit("disconnected");
            }
            this.scheduleReconnect();
        });

        ws.on("error", (err: Error) => {
            this.emit("error", err);
            // O evento 'close' será disparado depois, que fará a reconexão
        });
    }

    private handleMessage(msg: JarvisMessage): void {
        switch (msg.type) {
            case "prompt":
                this.emit("prompt", msg);
                break;
            case "shutdown":
                this.shouldReconnect = false;
                this.disconnect();
                break;
            case "pong":
                // Heartbeat OK
                break;
        }
    }

    private scheduleReconnect(): void {
        if (!this.shouldReconnect) {
            return;
        }
        this.clearReconnect();
        this.reconnectTimer = setTimeout(() => {
            if (this.shouldReconnect) {
                this.doConnect();
            }
        }, this.options.reconnectInterval);
    }

    private clearReconnect(): void {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }
}
