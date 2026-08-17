"use client";

import type { BoardSlot, DraftState } from "@/lib/types";
import { PositionBadge } from "@/components/PositionBadge";

const STATUS_COLORS: Record<string, string> = {
  OPEN: "border-slate-700 bg-slate-900/60 text-slate-400",
  FILLED: "border-slate-700 bg-slate-800 text-slate-200",
  KEEPER: "border-amber-700 bg-amber-900/30 text-amber-200",
};

export function DraftBoard({ state }: { state: DraftState }) {
  const teams = [...state.teams].sort((a, b) => a.draft_position - b.draft_position);
  const byRound = (round: number) =>
    state.board.filter((s) => s.round === round);

  const cellFor = (round: number, teamId: number): BoardSlot | null =>
    byRound(round).find((s) => s.drafting_team_id === teamId) ?? null;

  const roundRows = Array.from({ length: state.num_rounds }, (_, i) => i + 1);

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 bg-slate-900 px-2 py-1.5 text-left text-slate-500 font-medium">
              R
            </th>
            {teams.map((t) => (
              <th
                key={t.id}
                className="px-1.5 py-1.5 text-slate-400 font-semibold min-w-24"
              >
                {t.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {roundRows.map((round) => (
            <tr key={round}>
              <td className="sticky left-0 bg-slate-900 px-2 py-1.5 text-slate-500">
                {round}
              </td>
              {teams.map((t) => {
                const slot = cellFor(round, t.id);
                const traded =
                  slot && slot.original_team_id !== slot.drafting_team_id;
                return (
                  <td key={t.id} className="px-1 py-1">
                    {slot ? (
                      <div
                        className={`rounded-md border px-1.5 py-1 ${STATUS_COLORS[slot.status]}`}
                        title={slot.player_name ?? undefined}
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="truncate font-medium">
                            {slot.player_name ?? "—"}
                          </span>
                          {slot.status === "KEEPER" && (
                            <span className="badge bg-amber-500 text-slate-950">
                              K
                            </span>
                          )}
                          {traded && (
                            <span
                              className="badge bg-violet-500/20 text-violet-300"
                              title={`Originated with ${originalTeamName(state, slot)}`}
                            >
                              {originalTeamShort(state, slot)}
                            </span>
                          )}
                        </div>
                        {slot.player_name && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <PositionBadge position={slot.position ?? ""} size="xs" />
                            {slot.nfl_team && (
                              <span className="text-[10px] text-slate-500">
                                {slot.nfl_team}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="rounded-md border border-dashed border-slate-800 px-1.5 py-1 text-slate-700">
                        —
                      </div>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function originalTeamName(state: DraftState, slot: BoardSlot): string {
  return (
    state.teams.find((t) => t.id === slot.original_team_id)?.name ?? "?"
  );
}

function originalTeamShort(state: DraftState, slot: BoardSlot): string {
  const n = originalTeamName(state, slot);
  return n
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}