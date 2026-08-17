"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiJson } from "@/lib/api";
import type { LeagueSummary, LeagueStatus } from "@/lib/types";

interface TeamRow {
  name: string;
  manager_name: string;
}

interface CreatedLeague {
  access_token: string;
  teams: { draft_position: number; name: string; access_token: string }[];
}

export default function Home() {
  const [name, setName] = useState("Draft Night");
  const [season, setSeason] = useState("2026");
  const [numTeams, setNumTeams] = useState(12);
  const [numRounds, setNumRounds] = useState(15);
  const [teamNames, setTeamNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedLeague | null>(null);
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);

  useEffect(() => {
    apiJson<LeagueSummary[]>("/api/leagues")
      .then(setLeagues)
      .catch(() => setLeagues([]));
  }, []);

  const teamRows: TeamRow[] = useMemo(
    () =>
      Array.from({ length: numTeams }, (_, i) => ({
        name: teamNames[i]?.trim() || `Team ${i + 1}`,
        manager_name: "",
      })),
    [numTeams, teamNames],
  );

  async function create() {
    setError(null);
    try {
      const res = await apiJson<CreatedLeague>("/api/leagues", {
        method: "POST",
        body: JSON.stringify({
          name,
          season,
          num_teams: numTeams,
          num_rounds: numRounds,
          teams: teamRows,
        }),
      });
      setCreated(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create league");
    }
  }

  async function remove(id: number, accessToken: string) {
    if (!window.confirm("Delete this draft? This cannot be undone.")) return;
    try {
      await apiJson(`/api/draft/${accessToken}/admin/delete`, { method: "DELETE" });
      setLeagues((prev) => prev.filter((l) => l.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete draft");
    }
  }

  if (created) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
        <div className="max-w-2xl w-full">
          <h1 className="text-3xl font-bold mb-2">{name}</h1>
          <p className="text-slate-400 mb-6">
            League created. Share these links with your league:
          </p>
          <div className="space-y-3">
            <LinkRow
              label="Commissioner console"
              href={`/draft/${created.access_token}/admin`}
              desc="Configure teams, keepers, slots and run the draft."
            />
            <LinkRow
              label="TV / Display"
              href={`/draft/${created.access_token}/display`}
              desc="Read-only draft board for the projector."
            />
            {created.teams.map((t) => (
              <LinkRow
                key={t.draft_position}
                label={`Team link — ${t.name}`}
                href={`/draft/${created.access_token}/team/${t.access_token}`}
                desc={`Drafting interface for ${t.name}.`}
              />
            ))}
          </div>
          <Link
            href="/"
            className="mt-8 inline-block text-emerald-400 hover:underline"
          >
            Create another league
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
      <div className="max-w-xl w-full space-y-6">
        <div>
          <h1 className="text-4xl font-black tracking-tight">
            Draft<span className="text-emerald-400"> Night</span>
          </h1>
          <p className="text-slate-400 mt-1">
            Private fantasy-football draft command center
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="League name">
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Season">
              <input
                className="input"
                value={season}
                onChange={(e) => setSeason(e.target.value)}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Teams">
              <input
                className="input"
                type="number"
                min={2}
                max={32}
                value={numTeams}
                onChange={(e) => setNumTeams(Number(e.target.value))}
              />
            </Field>
            <Field label="Rounds">
              <input
                className="input"
                type="number"
                min={1}
                max={40}
                value={numRounds}
                onChange={(e) => setNumRounds(Number(e.target.value))}
              />
            </Field>
          </div>
          <Field label="Team names (optional, one per line)">
            <textarea
              className="input h-28 font-mono text-xs"
              placeholder={"Team 1\nTeam 2\n..."}
              value={teamNames.join("\n")}
              onChange={(e) =>
                setTeamNames(
                  e.target.value.split("\n").slice(0, numTeams),
                )
              }
            />
          </Field>
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <button
            onClick={create}
            className="w-full bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold rounded-xl py-3"
          >
            Create league
          </button>
        </div>

        {leagues.length > 0 && (
          <div className="space-y-3">
            <h2 className="text-lg font-bold text-slate-300">Existing drafts</h2>
            {leagues.map((l) => (
              <div
                key={l.id}
                className="flex items-center gap-3 bg-slate-900 border border-slate-800 rounded-xl p-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold truncate">{l.name}</span>
                    <StatusBadge status={l.status} />
                  </div>
                  <p className="text-sm text-slate-400">
                    {l.season} · {l.num_teams} teams · {l.num_rounds} rounds
                  </p>
                </div>
                <a
                  href={`/draft/${l.access_token}/admin`}
                  className="text-emerald-400 hover:underline text-sm shrink-0"
                >
                  Open
                </a>
                <button
                  onClick={() => remove(l.id, l.access_token)}
                  className="text-red-400 hover:text-red-300 text-sm shrink-0"
                  title="Delete draft"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

function StatusBadge({ status }: { status: LeagueStatus }) {
  const color =
    status === "LIVE"
      ? "bg-emerald-500/20 text-emerald-300"
      : status === "COMPLETED"
        ? "bg-sky-500/20 text-sky-300"
        : "bg-slate-500/20 text-slate-300";
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full border border-slate-700 ${color}`}
    >
      {status}
    </span>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs uppercase tracking-wider text-slate-400">
        {label}
      </span>
      {children}
    </label>
  );
}

function LinkRow({
  label,
  href,
  desc,
}: {
  label: string;
  href: string;
  desc: string;
}) {
  return (
    <a
      href={href}
      className="block bg-slate-900 border border-slate-800 rounded-xl p-4 hover:border-emerald-500 transition-colors"
    >
      <div className="font-semibold text-emerald-400">{label}</div>
      <div className="text-sm text-slate-400">{desc}</div>
    </a>
  );
}