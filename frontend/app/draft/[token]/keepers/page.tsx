"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { API_URL, apiJson } from "@/lib/api";
import type {
  KeeperPreviewCandidate,
  KeeperPreviewTeam,
  KeeperSetup,
} from "@/lib/types";

export default function KeeperAdminPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [setup, setSetup] = useState<KeeperSetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Draft CSV upload
  const [draftFile, setDraftFile] = useState<File | null>(null);
  const [draftYear, setDraftYear] = useState("");
  const [draftRole, setDraftRole] = useState<"previous" | "prior">("previous");
  const [useDraftId, setUseDraftId] = useState(0);

  // Yahoo config
  const [yLeague, setYLeague] = useState("");
  const [yGameId, setYGameId] = useState("");
  const [ySeason, setYSeason] = useState("");
  const [yWeek, setYWeek] = useState("");
  const [yKey, setYKey] = useState("");
  const [ySecret, setYSecret] = useState("");
  const [yCode, setYCode] = useState("");
  const [authUrl, setAuthUrl] = useState<string | null>(null);

  // Mapping
  const [mappings, setMappings] = useState<
    Record<number, { draft_name: string; yahoo_name: string }>
  >({});

  // Review
  const [review, setReview] = useState<KeeperPreviewTeam[]>([]);

  const editable = setup?.league.editable ?? false;

  const loadSetup = useCallback(async () => {
    setError(null);
    try {
      const s = await apiJson<KeeperSetup>(
        `/api/draft/${token}/admin/keepers/setup`,
      );
      setSetup(s);
      const m: Record<number, { draft_name: string; yahoo_name: string }> = {};
      for (const item of s.mappings) {
        m[item.team_id] = { draft_name: item.draft_name, yahoo_name: item.yahoo_name };
      }
      for (const item of s.suggested_mappings) {
        if (!m[item.team_id]) {
          m[item.team_id] = {
            draft_name: item.draft_name,
            yahoo_name: item.yahoo_name,
          };
        }
      }
      setMappings(m);
      setReview(s.preview.teams);
      setYLeague(s.yahoo.league_id_external);
      setYGameId(s.yahoo.game_id ? String(s.yahoo.game_id) : "");
      setYSeason(s.yahoo.season_id);
      setYWeek(s.yahoo.week ? String(s.yahoo.week) : "");
      setDraftYear(s.draft.previous_year || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [token]);

  useEffect(() => {
    loadSetup();
  }, [loadSetup]);

  function flash(ok: boolean, text: string) {
    setNotice(text);
    setTimeout(() => setNotice(null), 5000);
  }

  async function postForm(path: string, fd: FormData, label: string) {
    setError(null);
    setBusy(label);
    try {
      const res = await fetch(`${API_URL}${path}`, { method: "POST", body: fd });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Request failed",
        );
      }
      return body;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function postJson(path: string, body: unknown, label: string) {
    setError(null);
    setBusy(label);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res = await apiJson<any>(path, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      return res;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function uploadDraft() {
    if (!draftFile || !draftYear) return;
    const fd = new FormData();
    fd.append("file", draftFile);
    fd.append("year", draftYear);
    fd.append("role", draftRole);
    const body = await postForm(
      `/api/draft/${token}/admin/keepers/draft-csv`,
      fd,
      "Uploading draft…",
    );
    if (body) {
      flash(true, `Draft ${draftYear} (${draftRole}) loaded`);
      await loadSetup();
    }
  }

  async function useDraft() {
    if (!useDraftId) return;
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/use-draft`,
      { draft_league_id: useDraftId, role: draftRole },
      "Loading draft…",
    );
    if (body) {
      flash(true, `Loaded ${body.year} (${draftRole})`);
      setUseDraftId(0);
      await loadSetup();
    }
  }

  async function uploadRosters(files: FileList) {
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append("files", f);
    const body = await postForm(
      `/api/draft/${token}/admin/keepers/rosters-csv`,
      fd,
      "Uploading rosters…",
    );
    if (body) {
      flash(true, "Rosters loaded");
      await loadSetup();
    }
  }

  async function saveYahooConfig() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/yahoo-config`,
      {
        league_id_external: yLeague,
        game_id: yGameId ? Number(yGameId) : null,
        season_id: ySeason,
        week: yWeek ? Number(yWeek) : null,
        consumer_key: yKey,
        consumer_secret: ySecret,
      },
      "Saving Yahoo config…",
    );
    if (body) {
      flash(true, "Yahoo config saved");
      setYKey("");
      setYSecret("");
      await loadSetup();
    }
  }

  async function authorizeYahoo() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/yahoo/authorize`,
      {},
      "Preparing authorization…",
    );
    if (body) setAuthUrl(body.authorization_url as string);
  }

  async function completeYahooCode() {
    if (!yCode) return;
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/yahoo/callback`,
      { code: yCode },
      "Authorizing…",
    );
    if (body) {
      flash(true, "Yahoo authorized");
      setYCode("");
      setAuthUrl(null);
      await loadSetup();
    }
  }

  async function fetchRosters() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/fetch`,
      {},
      "Fetching rosters from Yahoo…",
    );
    if (body) {
      flash(true, `Fetched rosters for ${body.teams?.length ?? 0} teams`);
      await loadSetup();
    }
  }

  async function saveMappings() {
    const list = Object.entries(mappings).map(([teamId, m]) => ({
      team_id: Number(teamId),
      draft_name: m.draft_name,
      yahoo_name: m.yahoo_name,
    }));
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/mappings`,
      { mappings: list },
      "Saving mappings…",
    );
    if (body) {
      flash(true, "Mappings saved");
      await loadSetup();
    }
  }

  async function identify() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/identify`,
      {},
      "Identifying keepers…",
    );
    if (body) {
      setReview(body.preview as KeeperPreviewTeam[]);
      flash(
        true,
        `${body.total} keepable players identified`,
      );
      await loadSetup();
    }
  }

  async function saveKeepers() {
    const teams = review.map((t) => ({
      team_id: t.team_id,
      candidates: t.candidates.map((c) => ({
        player_name: c.player_name,
        position: c.position,
        nfl_team: c.nfl_team,
        player_id_external: c.player_id_external,
        cost_round: Number(c.cost_round),
        years_kept: c.years_kept,
        keepable_until_year: c.keepable_until_year,
      })),
    }));
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/save`,
      { teams },
      "Saving keepers…",
    );
    if (body) {
      flash(true, `Saved — ${body.stats?.created ?? 0} created`);
      await loadSetup();
    }
  }

  async function exportCsv() {
    setBusy("Exporting…");
    try {
      const data = await apiJson<{
        teams: { filename: string; csv: string }[];
      }>(`/api/draft/${token}/admin/keepers/export`);
      for (const f of data.teams) {
        const blob = new Blob([f.csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = f.filename;
        a.click();
        URL.revokeObjectURL(url);
      }
      flash(true, `Downloaded ${data.teams.length} roster CSVs`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy(null);
    }
  }

  function updateCandidate(
    teamIdx: number,
    candIdx: number,
    patch: Partial<KeeperPreviewCandidate>,
  ) {
    setReview((prev) =>
      prev.map((t, ti) =>
        ti === teamIdx
          ? {
              ...t,
              candidates: t.candidates.map((c, ci) =>
                ci === candIdx ? { ...c, ...patch } : c,
              ),
            }
          : t,
      ),
    );
  }

  function removeCandidate(teamIdx: number, candIdx: number) {
    setReview((prev) =>
      prev.map((t, ti) =>
        ti === teamIdx
          ? { ...t, candidates: t.candidates.filter((_, ci) => ci !== candIdx) }
          : t,
      ),
    );
  }

  const previewTotal = useMemo(
    () => review.reduce((n, t) => n + t.candidates.length, 0),
    [review],
  );

  if (error && !setup) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-red-400">{error}</p>
      </main>
    );
  }
  if (!setup) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-slate-400">Loading keeper console…</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 max-w-3xl mx-auto p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-black">Keeper Admin</h1>
          <p className="text-xs text-slate-400">
            {setup.league.name} · {setup.league.season}
            {setup.preview.saved_at ? " · last saved" : ""}
          </p>
        </div>
        <a
          href={`/draft/${token}/admin`}
          className="text-xs text-slate-400 hover:text-emerald-400"
        >
          ← Commissioner console
        </a>
      </header>

      {error && <div className="rounded-lg bg-red-900/40 px-3 py-2 text-sm text-red-300">{error}</div>}
      {notice && <div className="rounded-lg bg-emerald-900/40 px-3 py-2 text-sm text-emerald-300">{notice}</div>}

      {/* Step 1: previous-season drafts */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          1 · Previous draft CSVs (clickydraft export)
        </h2>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex-1 min-w-40">
            <label className="text-xs text-slate-500">Previous-season draft</label>
            <input
              type="file"
              accept=".csv"
              className="input"
              onChange={(e) => setDraftFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <input
            className="input w-24"
            placeholder="2025"
            value={draftYear}
            onChange={(e) => setDraftYear(e.target.value)}
          />
          <select
            className="input w-36"
            value={draftRole}
            onChange={(e) => setDraftRole(e.target.value as "previous" | "prior")}
          >
            <option value="previous">Previous season</option>
            <option value="prior">Season before (2-yr rule)</option>
          </select>
          <button
            className="btn-primary"
            disabled={!draftFile || !draftYear || !!busy}
            onClick={uploadDraft}
          >
            Upload
          </button>
        </div>
        <div className="mt-3 space-y-1 text-sm text-slate-400">
          {Object.entries(setup.draft.draft_counts).map(([year, byTeam]) => (
            <p key={year}>
              <span className="text-slate-200 font-semibold">{year}</span> ·{" "}
              {Object.entries(byTeam)
                .map(([team, count]) => `${team} (${count})`)
                .join(", ")}
            </p>
          ))}
          {!setup.draft.has_draft && (
            <p className="text-slate-600">
              No draft loaded yet. Upload a clickydraft CSV or use a completed
              draft from this app.
            </p>
          )}
        </div>

        <div className="mt-4 border-t border-slate-800 pt-4">
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-2">
            or use a completed draft from this app
          </h3>
          <div className="flex flex-wrap items-end gap-2">
            <select
              className="input flex-1 min-w-40"
              value={useDraftId}
              onChange={(e) => setUseDraftId(Number(e.target.value))}
            >
              <option value={0}>— select a completed draft —</option>
              {setup.previous_drafts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} · {d.season} · {d.picks} picks
                </option>
              ))}
            </select>
            <select
              className="input w-36"
              value={draftRole}
              onChange={(e) => setDraftRole(e.target.value as "previous" | "prior")}
            >
              <option value="previous">Previous season</option>
              <option value="prior">Season before (2-yr rule)</option>
            </select>
            <button
              className="btn-primary"
              disabled={!useDraftId || !!busy}
              onClick={useDraft}
            >
              Load
            </button>
          </div>
          {setup.previous_drafts.length === 0 && (
            <p className="text-xs text-slate-600 mt-1">
              No completed drafts in this app yet.
            </p>
          )}
        </div>
      </section>

      {/* Step 2: roster data (Yahoo or CSV) */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          2 · Roster data (Yahoo)
        </h2>
        <div className="grid grid-cols-2 gap-2 mb-3">
          <input
            className="input"
            placeholder="Yahoo league ID (e.g. 735068)"
            value={yLeague}
            onChange={(e) => setYLeague(e.target.value)}
          />
          <input
            className="input"
            placeholder="Game ID (449)"
            value={yGameId}
            onChange={(e) => setYGameId(e.target.value)}
          />
          <input
            className="input"
            placeholder="Season ID (2025)"
            value={ySeason}
            onChange={(e) => setYSeason(e.target.value)}
          />
          <input
            className="input"
            placeholder="Week (blank = current)"
            value={yWeek}
            onChange={(e) => setYWeek(e.target.value)}
          />
          <input
            className="input"
            placeholder="Consumer key"
            value={yKey}
            onChange={(e) => setYKey(e.target.value)}
          />
          <input
            className="input"
            type="password"
            placeholder="Consumer secret"
            value={ySecret}
            onChange={(e) => setYSecret(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-secondary" onClick={saveYahooConfig} disabled={!!busy}>
            Save Yahoo config
          </button>
          {setup.yahoo.configured && (
            <span className="text-xs text-slate-500">
              League {setup.yahoo.league_id_external || "—"} · key{" "}
              {setup.yahoo.consumer_key || "—"} ·{" "}
              {setup.yahoo.has_token ? "authorized" : "not authorized"}
            </span>
          )}
        </div>
        {setup.yahoo.configured && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn-secondary" onClick={authorizeYahoo} disabled={!!busy}>
                {setup.yahoo.has_token ? "Re-authorize" : "Authorize with Yahoo"}
              </button>
              {authUrl && (
                <span className="text-xs text-slate-400 break-all">
                  Open{" "}
                  <a href={authUrl} target="_blank" rel="noreferrer" className="text-emerald-400 underline">
                    this link
                  </a>
                  , authorize, then paste the code.
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <input
                className="input flex-1"
                placeholder="Paste authorization code here"
                value={yCode}
                onChange={(e) => setYCode(e.target.value)}
              />
              <button className="btn-primary" onClick={completeYahooCode} disabled={!yCode || !!busy}>
                Connect
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn-primary" onClick={fetchRosters} disabled={!!busy}>
                Fetch rosters from Yahoo
              </button>
              <input
                type="file"
                accept=".csv"
                multiple
                className="text-xs text-slate-500"
                onChange={(e) => {
                  if (e.target.files?.length) uploadRosters(e.target.files);
                  e.target.value = "";
                }}
              />
              <span className="text-xs text-slate-600">or upload roster CSVs</span>
            </div>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          {setup.rosters.player_count > 0
            ? `${setup.rosters.player_count} players across ${setup.rosters.teams.length} teams: ${setup.rosters.teams.join(", ")}`
            : "No roster data yet."}
        </p>
      </section>

      {/* Step 3: team name mapping */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          3 · Team name mapping
        </h2>
        <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 text-xs text-slate-500 mb-1 px-1">
          <span>App team</span>
          <span>Draft CSV column</span>
          <span>Yahoo team</span>
          <span />
        </div>
        <div className="space-y-2">
          {setup.teams.map((team) => {
            const m = mappings[team.id] ?? { draft_name: "", yahoo_name: "" };
            return (
              <div key={team.id} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2">
                <div className="flex items-center text-sm font-semibold truncate">
                  {team.name}
                </div>
                <select
                  className="input"
                  value={m.draft_name}
                  onChange={(e) =>
                    setMappings((prev) => ({
                      ...prev,
                      [team.id]: { ...prev[team.id], draft_name: e.target.value },
                    }))
                  }
                >
                  <option value="">— none —</option>
                  {setup.draft.draft_teams.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <select
                  className="input"
                  value={m.yahoo_name}
                  onChange={(e) =>
                    setMappings((prev) => ({
                      ...prev,
                      [team.id]: { ...prev[team.id], yahoo_name: e.target.value },
                    }))
                  }
                >
                  <option value="">— none —</option>
                  {setup.rosters.teams.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <span className="w-6" />
              </div>
            );
          })}
        </div>
        <button className="btn-secondary mt-3" onClick={saveMappings} disabled={!!busy}>
          Save mappings
        </button>
      </section>

      {/* Step 4: identify / review / save / export */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400">
            4 · Review &amp; save ({previewTotal})
          </h2>
          {setup.preview.saved_at && (
            <span className="text-xs text-slate-500">saved {setup.preview.saved_at}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2 mb-4">
          <button className="btn-primary" onClick={identify} disabled={!!busy}>
            Identify keepable players
          </button>
          <button
            className="btn-primary"
            disabled={review.length === 0 || !editable || !!busy}
            onClick={saveKeepers}
          >
            Save keepers
          </button>
          <button className="btn-secondary" onClick={exportCsv} disabled={!!busy}>
            Export per-team CSVs
          </button>
        </div>
        {setup.preview.warnings.length > 0 && (
          <ul className="mb-4 space-y-0.5 text-xs text-amber-300/90 bg-amber-900/20 rounded-lg p-2">
            {setup.preview.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
        {review.length === 0 ? (
          <p className="text-sm text-slate-500">
            Run the identify step to compute costs from the drafts and
            rosters.
          </p>
        ) : (
          <div className="space-y-4">
            {review.map((team, ti) => (
              <div key={team.team_id}>
                <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-1">
                  {team.team_name} ({team.candidates.length})
                </h3>
                <div className="space-y-1.5">
                  {team.candidates.map((c, ci) => (
                    <div
                      key={`${c.player_name}-${ci}`}
                      className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm"
                    >
                      <span className="flex-1 min-w-0">
                        <span className="font-semibold truncate">{c.player_name}</span>{" "}
                        <span className="text-xs text-slate-500">
                          {c.position} · {c.nfl_team}
                          {c.years_kept === 1 ? " · last year" : ""}
                        </span>
                      </span>
                      <input
                        className="input w-20"
                        type="number"
                        min={1}
                        value={c.cost_round}
                        onChange={(e) =>
                          updateCandidate(ti, ci, {
                            cost_round: Number(e.target.value),
                          })
                        }
                      />
                      <button
                        className="text-xs text-red-400 hover:underline"
                        onClick={() => removeCandidate(ti, ci)}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                  {team.candidates.length === 0 && (
                    <p className="text-xs text-slate-600">No keepable players.</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}