import { useEffect, useRef, useState, type FormEvent } from "react";
import { Send, X } from "lucide-react";
import { api } from "../lib/api";
import { errorMessage, useApp } from "../lib/store";
import { Button, cx, inputClass } from "./ui";

interface Message {
  from: "you" | "assistant";
  text: string;
  grounding?: string;
  failed?: boolean;
}

const STARTERS = ["Give me an overview", "Which alerts are open?", "Show gas flares", "Status of Bhilai", "How does the classification work?"];

export function AssistantPanel() {
  const { assistantOpen, setAssistantOpen } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  async function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setMessages((m) => [...m, { from: "you", text: trimmed }]);
    setQuestion("");
    setBusy(true);
    try {
      const answer = await api.ask(trimmed);
      setMessages((m) => [...m, { from: "assistant", text: answer.answer, grounding: answer.grounding }]);
    } catch (e) {
      setMessages((m) => [...m, { from: "assistant", text: errorMessage(e), failed: true }]);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    ask(question);
  }

  if (!assistantOpen) return null;
  return (
    <div className="no-print fixed bottom-4 right-4 z-[2600] flex h-[520px] w-[400px] max-w-[calc(100vw-2rem)] flex-col rounded-md border border-line bg-panel shadow-2xl">
      <div className="flex items-start justify-between border-b border-line px-4 py-3">
        <div>
          <div className="text-[16px] font-semibold">Query assistant</div>
          <div className="text-[13px] text-muted">Rule-based: answers are computed from stored detections, not generated text.</div>
        </div>
        <button className="rounded-lg p-1 text-muted hover:bg-sunk" onClick={() => setAssistantOpen(false)} aria-label="Close assistant">
          <X size={17} />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-1.5">
            {STARTERS.map((s) => (
              <button key={s} onClick={() => ask(s)} className="rounded-lg border border-line px-2 py-1 text-[13.5px] text-ink-2 hover:bg-sunk">
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={cx("max-w-[92%] rounded-lg px-3 py-2 text-[14.5px] leading-relaxed", m.from === "you" ? "ml-auto bg-accent text-white" : m.failed ? "bg-crit-soft" : "bg-sunk")}>
            {m.text}
            {m.grounding && <div className="mt-1 text-[12.5px] text-muted">{m.grounding}</div>}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={submit} className="flex gap-2 border-t border-line p-3">
        <input className={inputClass} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about a facility, a class or open alerts" maxLength={500} />
        <Button type="submit" variant="primary" icon={Send} loading={busy} aria-label="Send" />
      </form>
    </div>
  );
}
