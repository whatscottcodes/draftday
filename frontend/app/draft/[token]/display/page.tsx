"use client";

import { use } from "react";
import { DraftBoard } from "@/components/DraftBoard";
import { useDraftState } from "@/hooks/useDraftState";
import { API_URL } from "@/lib/api";

export default function DisplayPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const { state, connected, error } = useDraftState(token);

  if (error) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-8">
        <p className="text-red-400">Failed to load draft: {error}</p>
      </main>
    );
  }
  if (!state) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-8">
        <p className="text-slate-400">Loading draft…</p>
      </main>
    );
  }

  const onClock = state.current_slot
    ? state.teams.find((t) => t.id === state.current_slot?.drafting_team_id)
    : undefined;
  const lastPicks = state.recent_picks.slice(0, 5);

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-black tracking-tight">
            {state.league_name}
            <span className="text-slate-500 font-normal text-xl">
              {" "}
              · {state.season}
            </span>
          </h1>
          <p className="text-sm text-slate-400">
            {state.status === "LIVE" && `${state.available_count} players available`}
            {state.status === "COMPLETED" && "Draft complete"}
            {state.status === "SETUP" && "Not started"}
            {state.status === "READY" && "Ready"}
            {!connected && " · reconnecting…"}
          </p>
        </div>
        {onClock && state.status === "LIVE" && (
          <div className="text-right">
            <div className="text-sm text-slate-400">
              Pick {state.current_slot!.pick_number} · Round{" "}
              {state.current_slot!.round}
            </div>
            <div className="text-4xl font-black text-emerald-400">
              {onClock.name}
            </div>
          </div>
        )}
        {state.status === "COMPLETED" && (
          <div className="text-4xl font-black text-amber-400">COMPLETE</div>
        )}
      </header>

      {lastPicks.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {lastPicks.map((p) => (
            <div
              key={p.id}
              className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm"
            >
              <span className="text-slate-500">#{p.pick_number}</span>{" "}
              <span className="text-emerald-400">{p.player_name}</span>{" "}
              <span className="text-slate-500">
                ({p.position}) — {p.team_name}
              </span>
            </div>
          ))}
        </div>
      )}

      <DraftBoard state={state} />

      {state.top_available.length > 0 && (
        <section>
          <h2 className="text-xs uppercase tracking-widest text-slate-500 mb-2">
            Top available
          </h2>
          <div className="flex flex-wrap gap-2">
            {state.top_available.slice(0, 12).map((p) => (
              <span
                key={p.player_id}
                className="badge border border-slate-800 bg-slate-900 text-slate-300"
              >
                {p.rank !== null && (
                  <span className="text-slate-500 mr-1">{p.rank}.</span>
                )}
                {p.name} <span className="text-slate-500 ml-1">{p.position}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <footer className="text-xs text-slate-600 pt-2">
        API: {API_URL} · Draft Night V1
      </footer>
    </main>
  );
}