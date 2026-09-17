import { X } from "lucide-react";
import { useApp } from "../lib/store";
import { cx } from "./ui";

export function Toasts() {
  const { toasts, dismissToast } = useApp();
  if (toasts.length === 0) return null;
  return (
    <div className="no-print fixed bottom-4 left-4 z-[3500] flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-2" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cx(
            "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-[14.5px] shadow-lg",
            toast.tone === "error" ? "border-crit/40 bg-crit-soft" : toast.tone === "success" ? "border-good/40 bg-good-soft" : "border-line bg-panel",
          )}
        >
          <span className="min-w-0 flex-1 leading-relaxed">{toast.message}</span>
          <button onClick={() => dismissToast(toast.id)} className="rounded-lg p-0.5 text-muted hover:text-ink" aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

export function SignInHint({ permission, action }: { permission: string; action: string }) {
  const { user, can, setSignInOpen } = useApp();
  if (can(permission)) return null;
  return (
    <div className="rounded-lg border border-line bg-sunk px-3 py-2 text-[14px] text-ink-2">
      {user ? (
        <>Your role ({user.role}) cannot {action}. Sign in as commander to continue.</>
      ) : (
        <>
          <button className="font-semibold text-accent hover:underline" onClick={() => setSignInOpen(true)}>
            Sign in
          </button>{" "}
          to {action}.
        </>
      )}
    </div>
  );
}
