"use client";

import { use, useEffect, useState } from "react";
import { apiJsonRetry } from "@/lib/api";
import type { RostersState } from "@/lib/types";
import { PositionBadge } from "@/components/PositionBadge";

export default function RostersPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [state, setState] = useState<RostersState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiJsonRetry<RostersState>(`/api/draft/${token}/rosters`)
      .then((s) => {
        setState(s);
        setError(null);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load rosters"),
      );
  }, [token]);

  if (error && !state) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-red-400">{error}</p>
      </main>
    );
  }
  if (!state) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-slate-400">Loading rosters…</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6 max-w-6xl mx-auto">
      <header className="mb-6">
        <a
          href={`/draft/${token}/display`}
          className="text-sm text-slate-400 hover:text-emerald-400"
        >
          ← TV board
        </a>
        <h1 className="text-3xl font-black mt-1">
          {state.league_name}{" "}
          <span className="text-slate-500 font-normal text-xl">
            · {state.season}
          </span>
        </h1>
        <p className="text-sm text-slate-400">
          Team rosters · {state.num_teams} teams · {state.num_rounds} rounds ·
          status{" "}
          <span className="badge bg-emerald-500/20 text-emerald-300">
            {state.status}
          </span>
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {state.teams.map((team) => (
          <section
            key={team.team_id}
            className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4"
          >
            <h2 className="font-bold mb-2">
              <span className="text-slate-500">{team.draft_position}.</span>{" "}
              {team.team_name}
            </h2>
            <div className="space-y-1">
              {team.roster.map((r) => (
                <div
                  key={r.slot}
                  className="flex items-center gap-2 text-sm"
                >
                  <span className="w-12 text-xs font-semibold text-slate-500">
                    {r.slot}
                  </span>
                  <PositionBadge position={r.position} size="xs" />
                  {r.player ? (
                    <span className="truncate text-slate-200">
                      {r.player.player_name}
                      <span className="text-xs text-slate-500 ml-1">
                        {r.player.nfl_team ? r.player.nfl_team : ""}
                      </span>
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </div>
              ))}
            </div>
            {team.bench.length > 0 && (
              <>
                <h3 className="text-xs uppercase tracking-widest text-slate-500 mt-3 mb-1">
                  Bench ({team.bench.length})
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {team.bench.map((p) => (
                    <span
                      key={p.player_id}
                      className="badge bg-slate-800 text-slate-300 border border-slate-700"
                    >
                      {p.player_name}{" "}
                      <PositionBadge position={p.position} size="xs" />
                    </span>
                  ))}
                </div>
              </>
            )}
            {team.roster.every((r) => !r.player) && team.bench.length === 0 && (
              <p className="text-sm text-slate-600">No players yet.</p>
            )}
          </section>
        ))}
      </div>
    </main>
  );
}