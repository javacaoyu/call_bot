/** 通话记录 API（WBS 5.3）：列表与详情。 */

export interface TranscriptBubble {
  role: "user" | "bot" | "mark";
  text: string;
  ts: number;
}

export interface CallRecord {
  id: string;
  started_at: string;
  ended_at: string;
  duration_s: number;
  status: "connected" | "no_answer" | "error";
  status_text: string;
  interrupt_count: number;
  transcript: TranscriptBubble[];
}

export async function fetchCalls(limit = 50): Promise<CallRecord[]> {
  const resp = await fetch(`/api/calls?limit=${limit}`);
  if (!resp.ok) {
    throw new Error(`读取通话记录失败（${resp.status}）`);
  }
  return (await resp.json()) as CallRecord[];
}
