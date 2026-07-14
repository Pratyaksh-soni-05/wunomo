'use client';
import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "@/lib/api";

const PERSONALITY_MODES = ["engineer", "founder", "analyst", "auditor"];
const OPERATION_MODES   = ["advisory", "assisted", "autonomous", "audit"];

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  pending_approvals?: any[];
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([{
    role: "assistant",
    content: "Hello! I'm **AXIOM**, your AI DataOps Engineer.

I can help you:
- 🔍 Profile and inspect data sources
- ⚡ Trigger and monitor pipelines
- ✅ Run quality checks
- 🚨 Triage incidents
- 📊 Generate reports

What would you like to do?",
    timestamp: new Date().toISOString(),
  }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(() => crypto.randomUUID());
  const [personality, setPersonality] = useState("engineer");
  const [operation, setOperation] = useState("assisted");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = { role: "user", content: input, timestamp: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const r = await api.post("/api/v1/chat/", {
        message: input, session_id: sessionId,
        personality_mode: personality, operation_mode: operation,
      });
      setMessages(prev => [...prev, {
        role: "assistant", content: r.data.response,
        timestamp: r.data.timestamp, pending_approvals: r.data.pending_approvals,
      }]);
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Connection error. Check your API key and backend.";
      setMessages(prev => [...prev, {
        role: "assistant", content: `⚠️ ${detail}`, timestamp: new Date().toISOString(),
      }]);
    } finally { setLoading(false); }
  };

  const SUGGESTIONS = [
    "Show me all data sources",
    "Run quality checks on demo pipeline",
    "What is the system health?",
    "List open incidents",
  ];

  return (
    <div className="flex flex-col h-screen bg-gray-950">
      <div className="border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white text-sm font-bold">A</div>
          <div>
            <p className="text-white font-medium text-sm">AXIOM</p>
            <p className="text-gray-500 text-xs">AI DataOps Engineer · Session {sessionId.slice(0, 8)}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <select value={personality} onChange={e => setPersonality(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-gray-300 text-xs rounded-lg px-2 py-1.5">
            {PERSONALITY_MODES.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <select value={operation} onChange={e => setOperation(e.target.value)}
            className="bg-gray-900 border border-gray-700 text-gray-300 text-xs rounded-lg px-2 py-1.5">
            {OPERATION_MODES.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            {msg.role === "assistant" && (
              <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold text-white shrink-0 mt-1">A</div>
            )}
            <div className={`max-w-[78%] rounded-2xl px-4 py-3 text-sm ${
              msg.role === "user"
                ? "bg-blue-600 text-white rounded-br-sm"
                : "bg-gray-900 border border-gray-800 text-gray-200 rounded-bl-sm"
            }`}>
              {msg.role === "assistant"
                ? <ReactMarkdown className="prose prose-invert prose-sm max-w-none">{msg.content}</ReactMarkdown>
                : msg.content}
              {msg.pending_approvals && msg.pending_approvals.length > 0 && (
                <div className="mt-3 p-2 bg-yellow-900/30 border border-yellow-600/30 rounded-lg text-yellow-300 text-xs">
                  ⚠️ {msg.pending_approvals.length} action(s) pending approval — visit Governance → Approvals
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold shrink-0">A</div>
            <div className="bg-gray-900 border border-gray-800 rounded-2xl px-4 py-3">
              <div className="flex gap-1">
                {[0,1,2].map(i => (
                  <div key={i} className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }} />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {messages.length === 1 && (
        <div className="px-4 pb-2 flex gap-2 flex-wrap justify-center">
          {SUGGESTIONS.map(s => (
            <button key={s} onClick={() => { setInput(s); }}
              className="text-xs px-3 py-1.5 bg-gray-900 border border-gray-700 text-gray-400 rounded-full hover:border-blue-500 hover:text-blue-400 transition">
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="border-t border-gray-800 px-4 py-4">
        <div className="flex gap-2 max-w-4xl mx-auto">
          <input
            value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }}}
            placeholder="Ask AXIOM about your data pipelines..."
            className="flex-1 bg-gray-900 border border-gray-700 focus:border-blue-500 text-gray-100 placeholder-gray-500 rounded-xl px-4 py-3 text-sm outline-none transition"
          />
          <button onClick={send} disabled={loading || !input.trim()}
            className="px-5 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-xl text-sm font-medium transition">
            Send
          </button>
        </div>
        <p className="text-center text-gray-600 text-xs mt-2">
          Mode: {personality} · {operation} · Session: {sessionId.slice(0, 8)}
        </p>
      </div>
    </div>
  );
}
