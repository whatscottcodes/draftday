"use client";

import type { BoardSlot, DraftState } from "@/lib/types";
import { positionColor } from "@/lib/positions";

const STATUS_COLORS: Record<string, string> = {
  OPEN: "border border-slate-700 bg-slate-900 text-slate-500",
  FILLED: "border border-slate-600 bg-slate-800 text-slate-100",
  KEEPER: "border border-amber-500 bg-amber-950/80 text-amber-200",
};

export function DraftBoard({ state }: { state: DraftState }) {
  const teams = [...state.teams].sort((a, b) => a.draft_position - b.draft_position);
  const byRound = (round: number) =>
    state.board.filter((s) => s.round === round);

  const cellFor = (round: number, teamId: number): BoardSlot[] =>
    byRound(round)
      .filter((s) => s.drafting_team_id === teamId)
      .sort((a, b) => a.pick_number - b.pick_number);

  const roundRows = Array.from({ length: state.num_rounds }, (_, i) => i + 1);

  return (
    <div className="overflow-x-auto border-2 border-t-slate-500 border-l-slate-500 border-b-black border-r-black bg-slate-950 shadow-[2px_2px_0px_#000000]">
      <table className="w-full border-collapse text-xs font-sans">
        <thead>
          <tr className="border-b-2 border-black bg-gradient-to-r from-blue-950 via-indigo-950 to-blue-950 text-white">
            <th className="sticky left-0 z-10 bg-blue-950 px-2.5 py-2 text-center text-yellow-300 font-mono font-black border-r-2 border-black border-b-2">
              RND
            </th>
            {teams.map((t) => (
              <th
                key={t.id}
                className="px-2 py-2 text-center font-bold text-white min-w-28 border-r border-slate-700/80 text-[11px] uppercase tracking-wide bg-gradient-to-b from-blue-900 to-blue-950"
              >
                <div className="text-[9px] text-yellow-300 font-mono">
                  #{t.draft_position}
                </div>
                <div className="truncate font-black">{t.name}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {roundRows.map((round) => (
            <tr
              key={round}
              className={round % 2 === 0 ? "bg-slate-900/60" : "bg-slate-950"}
            >
              <td className="sticky left-0 z-10 bg-slate-900 px-2 py-1.5 text-center font-mono font-bold text-yellow-400 border-r-2 border-black border-b border-slate-800">
                {round}
              </td>
              {teams.map((t) => {
                const slots = cellFor(round, t.id);
                return (
                  <td
                    key={t.id}
                    className="p-1 border-r border-b border-slate-800/80 align-top"
                  >
                    {slots.length > 0 ? (
                      <div className="flex flex-col gap-1">
                        {slots.map((slot) => {
                          const traded =
                            slot.original_team_id !== slot.drafting_team_id;
                          return slot.player_name ? (
                            <div
                              key={slot.slot_id}
                              className="rounded-none px-1.5 py-1 select-none border-t border-l border-t-white/80 border-l-white/80 border-b-2 border-r-2 border-b-black border-r-black"
                              style={{
                                backgroundColor: positionColor(slot.position ?? ""),
                                color: "#000000",
                              }}
                              title={`Pick #${slot.pick_number}: ${slot.player_name}`}
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="truncate font-black text-[11px] leading-tight">
                                  {slot.player_name}
                                </span>
                                <div className="flex gap-0.5 shrink-0">
                                  {(slot.pick_type === "keeper" || slot.status === "KEEPER") && (
                                    <span
                                      className="inline-block bg-black text-amber-300 px-1 py-0 text-[8px] font-black border border-amber-400"
                                      title="Logged as keeper"
                                    >
                                      K
                                    </span>
                                  )}
                                  {traded && (
                                    <span
                                      className="inline-block bg-black text-cyan-300 px-1 py-0 text-[8px] font-black border border-cyan-400"
                                      title={`Originated with ${originalTeamName(state, slot)}`}
                                    >
                                      {originalTeamShort(state, slot)}
                                    </span>
                                  )}
                                </div>
                              </div>
                              <div className="text-[9px] font-black opacity-90 mt-0.5 flex justify-between">
                                <span>
                                  {slot.position}
                                  {slot.nfl_team ? ` · ${slot.nfl_team}` : ""}
                                </span>
                                <span className="font-mono text-[8px] opacity-75">
                                  #{slot.pick_number}
                                </span>
                              </div>
                            </div>
                          ) : (
                            <div
                              key={slot.slot_id}
                              className={`rounded-none px-1.5 py-1 text-center font-mono text-[10px] ${STATUS_COLORS[slot.status]}`}
                            >
                              <span className="opacity-40">#{slot.pick_number}</span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="rounded-none border border-dashed border-slate-800 px-1.5 py-1 text-center text-slate-700 text-[10px] font-mono">
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
