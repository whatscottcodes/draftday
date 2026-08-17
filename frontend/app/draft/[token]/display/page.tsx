"use client";

import { use } from "react";
import { DraftBoard } from "@/components/DraftBoard";
import { useDraftState } from "@/hooks/useDraftState";
import { API_URL } from "@/lib/api";
import { positionColor } from "@/lib/positions";

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
          <div className="flex gap-3 text-sm text-slate-400 mt-1">
            <a
              href={`/draft/${token}/admin`}
              className="text-emerald-400 hover:underline"
            >
              ← Commissioner
            </a>
            <a
              href={`/draft/${token}/rosters`}
              className="text-emerald-400 hover:underline"
            >
              Rosters
            </a>
          </div>
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
              className="rounded-lg border px-3 py-1.5 text-sm font-medium"
              style={{
                backgroundColor: positionColor(p.position),
                borderColor: positionColor(p.position),
                color: "#0f172a",
              }}
            >
              <span className="opacity-60">#{p.pick_number}</span>{" "}
              <span className="font-bold">{p.player_name}</span>{" "}
              <span className="font-black">{p.position}</span>{" "}
              <span className="opacity-70">— {p.team_name}</span>
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
                className="badge font-medium"
                style={{
                  backgroundColor: positionColor(p.position),
                  borderColor: positionColor(p.position),
                  color: "#0f172a",
                }}
              >
                {p.rank !== null && (
                  <span className="opacity-60 mr-1">{p.rank}.</span>
                )}
                {p.name}
                <span className="ml-1 font-black">{p.position}</span>
                {p.bye_week && (
                  <span className="opacity-60 ml-1">BYE {p.bye_week}</span>
                )}
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