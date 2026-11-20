/** WebRTC 信令客户端：与后端 /ws/signal 交换 offer/answer/ICE。 */

export interface SignalMessage {
  type: "offer" | "answer" | "ice" | "error";
  sdp?: string;
  candidate?: RTCIceCandidateInit | null;
  detail?: string;
}

export class SignalingClient {
  private ws: WebSocket | null = null;

  connect(url: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(url);
      this.ws.onopen = () => resolve();
      this.ws.onerror = () => reject(new Error("信令连接失败"));
    });
  }

  send(message: SignalMessage): void {
    this.ws?.send(JSON.stringify(message));
  }

  onMessage(handler: (msg: SignalMessage) => void): void {
    if (this.ws) {
      this.ws.onmessage = (e) => {
        handler(JSON.parse(e.data as string) as SignalMessage);
      };
    }
  }

  onClose(handler: () => void): void {
    if (this.ws) {
      this.ws.onclose = handler;
    }
  }

  close(): void {
    this.ws?.close();
    this.ws = null;
  }
}
