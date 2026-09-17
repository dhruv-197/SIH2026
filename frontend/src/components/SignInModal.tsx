import { useState, type FormEvent } from "react";
import { LogIn } from "lucide-react";
import { errorMessage, useApp } from "../lib/store";
import { LogoMark } from "./Logo";
import { Button, Callout, Field, Modal, inputClass } from "./ui";

export function SignInModal() {
  const { signInOpen, setSignInOpen, signIn, demoPasswords } = useApp();
  const [username, setUsername] = useState("analyst");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username, password);
      setPassword("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={signInOpen} onClose={() => setSignInOpen(false)} leading={<LogoMark size={40} />} title="Sign in" subtitle="Viewing is open; changing data, triaging incidents and settings need a role." width="max-w-md">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label="Role">
          <select className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)}>
            <option value="analyst">Analyst - sync data, upload CSV, triage incidents</option>
            <option value="commander">Commander - analyst rights plus settings, drills, test alerts</option>
          </select>
        </Field>
        <Field label="Password">
          <input className={inputClass} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        {demoPasswords && (
          <Callout tone="warn" title="Default demo passwords are active">
            analyst / <code>analyst-demo</code>, commander / <code>commander-demo</code>. Set ANALYST_PASSWORD and COMMANDER_PASSWORD before any real deployment.
          </Callout>
        )}
        {error && <Callout tone="error">{error}</Callout>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={() => setSignInOpen(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" icon={LogIn} loading={busy}>
            Sign in
          </Button>
        </div>
      </form>
    </Modal>
  );
}
