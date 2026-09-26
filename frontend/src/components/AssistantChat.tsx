import { useState } from "react";
import axios from "axios";
import { explainAnalysis } from "../services/api";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export function AssistantChat({ analysisId }: { analysisId: string | null }) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAsk() {
    if (!analysisId || !question.trim()) return;
    const userMessage: ChatMessage = { role: "user", text: question };
    setMessages((prev) => [...prev, userMessage]);
    setQuestion("");
    setLoading(true);
    setError(null);

    try {
      const { explanation } = await explainAnalysis(analysisId, userMessage.text);
      setMessages((prev) => [...prev, { role: "assistant", text: explanation }]);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.data?.detail) {
        setError(String(err.response.data.detail));
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to reach the AI assistant.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <p className="text-xs uppercase tracking-wide text-slate-400">
        Ask the AI assistant
      </p>

      <div className="mt-3 flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <p className="text-sm text-slate-500">
            Ask why an anomaly was flagged, what NDCI/NDTI mean, or what to
            investigate next.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "user"
                ? "ml-auto max-w-[85%] rounded-lg bg-aqua-600/20 px-3 py-2 text-sm text-aqua-100"
                : "mr-auto max-w-[85%] rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-100"
            }
          >
            {m.text}
          </div>
        ))}
        {loading && (
          <p className="text-xs text-slate-500">Assistant is thinking…</p>
        )}
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>

      <div className="mt-3 flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          disabled={!analysisId}
          placeholder={
            analysisId ? "Ask a question…" : "Run an analysis first"
          }
          className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-50"
        />
        <button
          onClick={handleAsk}
          disabled={!analysisId || loading || !question.trim()}
          className="rounded-lg bg-aqua-600 px-4 py-2 text-sm font-medium text-white hover:bg-aqua-500 disabled:opacity-50"
        >
          Ask
        </button>
      </div>
    </div>
  );
}
