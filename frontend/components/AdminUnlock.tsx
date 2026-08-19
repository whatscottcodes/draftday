"use client";

import { useState } from "react";
import { setAdminPasscode } from "@/lib/api";

export default function AdminUnlock({
  onUnlocked,
  message = "COMMISSIONER PASSCODE REQUIRED",
}: {
  onUnlocked: () => void;
  message?: string;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) {
      setError("Enter the commissioner passcode");
      return;
    }
    setAdminPasscode(value.trim());
    setError(null);
    onUnlocked();
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-4">
      <div className="retro-panel w-full max-w-md border-2 border-t-slate-300 border-l-slate-300 border-b-black border-r-black bg-slate-950 p-0 shadow-[4px_4px_0px_#000000]">
        <div className="retro-titlebar-gold">
          <span className="flex items-center gap-1.5 font-black">
            <span>🔒</span> COMMISSIONER ACCESS
          </span>
          <span className="text-[10px] font-mono text-yellow-300">
            LOCKED
          </span>
        </div>
        <form onSubmit={submit} className="p-4 space-y-3">
          <p className="text-xs text-slate-300 font-mono leading-relaxed">
            {message}
          </p>
          <input
            type="password"
            className="input"
            placeholder="Enter passcode…"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError(null);
            }}
            autoFocus
          />
          {error && (
            <div className="border-2 border-red-500 bg-red-950 p-2 text-red-200 text-xs font-mono font-bold">
              ⚠️ ERROR: {error}
            </div>
          )}
          <button type="submit" className="w-full btn btn-gold py-2.5">
            <span>🔓</span> UNLOCK
          </button>
        </form>
      </div>
    </main>
  );
}