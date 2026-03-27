import { useCallback, useEffect, useMemo, useState } from "react";
import UniverseModal from "./UniverseModal";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const BASE_DEFAULTS = {
  top_n_per_side: 10,
  universe_min_market_cap_b: 3.0,
  universe_min_dollar_vol_m: 50.0,
  universe_min_price: 10.0,
  universe_size: 1000,
  lookback_days: 320,
  pivot_window: 5,
  min_wave_a_pct: 12.0,
  min_b_retrace: 0.382,
  max_b_retrace: 0.886,
  ideal_b_retrace: 0.618,
  max_days_since_b: 30,
  min_c_progress: 0.03,
  max_c_progress: 0.45,
  bullish_daily_rsi_min: 45.0,
  bullish_daily_rsi_max: 67.0,
  bearish_daily_rsi_min: 33.0,
  bearish_daily_rsi_max: 55.0,
  min_volume_ratio: 0.9,
  require_ema_confirmation: true,
};

const COLORS = {
  ink: "#191510",
  paper: "#f4efe6",
  panel: "#fdfbf7",
  line: "#ded3c2",
  muted: "#6e6559",
  faint: "#9d927f",
  bullish: "#1f7a5c",
  bearish: "#8d4033",
  neutral: "#76531f",
  ocean: "#265d7a",
  alert: "#fff3ed",
  alertLine: "#e5b29e",
};

const GROUPS = [
  {
    label: "Universe",
    fields: [
      ["top_n_per_side", "Top N / side", 5, 25, 1, ""],
      ["universe_min_market_cap_b", "Min market cap", 1, 25, 0.5, "$B"],
      ["universe_min_dollar_vol_m", "30D avg dollar volume", 25, 300, 5, "$M"],
      ["universe_min_price", "Min stock price", 5, 50, 1, "$"],
      ["universe_size", "Universe size", 200, 1500, 50, "tickers"],
      ["lookback_days", "Lookback days", 180, 520, 5, "days"],
    ],
  },
  {
    label: "Wave Structure",
    fields: [
      ["pivot_window", "Pivot window", 3, 9, 1, "bars"],
      ["min_wave_a_pct", "Min Wave A move", 6, 30, 1, "%"],
      ["min_b_retrace", "Min B retrace", 0.2, 0.7, 0.01, "ratio"],
      ["max_b_retrace", "Max B retrace", 0.5, 1.0, 0.01, "ratio"],
      ["ideal_b_retrace", "Ideal B retrace", 0.382, 0.786, 0.01, "ratio"],
      ["max_days_since_b", "Max days since B", 5, 60, 1, "days"],
    ],
  },
  {
    label: "Wave C Timing",
    fields: [
      ["min_c_progress", "Min C progress", 0.01, 0.2, 0.01, "ratio"],
      ["max_c_progress", "Max C progress", 0.15, 0.8, 0.01, "ratio"],
      ["min_volume_ratio", "5D / 20D volume ratio", 0.5, 2.5, 0.05, "x"],
      ["require_ema_confirmation", "Require EMA confirmation", 0, 1, 1, "bool"],
    ],
  },
  {
    label: "Bullish Momentum",
    fields: [
      ["bullish_daily_rsi_min", "Bullish RSI min", 20, 60, 1, ""],
      ["bullish_daily_rsi_max", "Bullish RSI max", 30, 80, 1, ""],
    ],
  },
  {
    label: "Bearish Momentum",
    fields: [
      ["bearish_daily_rsi_min", "Bearish RSI min", 15, 60, 1, ""],
      ["bearish_daily_rsi_max", "Bearish RSI max", 25, 80, 1, ""],
    ],
  },
];

function fmt(value, digits = 1) {
  return value == null || Number.isNaN(Number(value)) ? "-" : Number(value).toFixed(digits);
}

function changedCount(a, b) {
  return Object.keys(a).filter((key) => a[key] !== b[key]).length;
}

async function fetchJson(path, options = {}) {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body?.detail || body?.message || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return body;
}

function ProgressBar({ title, progress, color }) {
  const percent = Math.max(0, Math.min(100, Number(progress?.percent || 0)));
  return (
    <div className="progress">
      <div className="progress-head">
        <strong>{title}</strong>
        <span>{percent}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${percent}%`, background: color }} />
      </div>
      <div className="progress-copy">{progress?.message || "Queued"}</div>
    </div>
  );
}

function Field({ spec, value, savedValue, onChange }) {
  const [key, label, min, max, step, unit] = spec;
  const modified = value !== savedValue;
  if (key === "require_ema_confirmation") {
    return (
      <button className={`toggle ${value ? "on" : ""}`} onClick={() => onChange(key, !value)} type="button">
        <span>{label}</span>
        <span>{value ? "On" : "Off"}</span>
      </button>
    );
  }
  return (
    <label className={`field ${modified ? "modified" : ""}`}>
      <div className="field-head">
        <span>{label}</span>
        <em>{unit}</em>
      </div>
      <div className="field-body">
        <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(key, Number(e.target.value))} />
        <input type="number" min={min} max={max} step={step} value={value} onChange={(e) => onChange(key, Number(e.target.value))} />
      </div>
    </label>
  );
}

function CandidateTable({ title, tag, color, rows, emptyMessage }) {
  return (
    <section className="panel candidates" style={{ borderTop: `3px solid ${color}` }}>
      <div className="strategy-head">
        <div>
          <span className="tag" style={{ color, borderColor: color }}>{tag}</span>
          <h3>{title}</h3>
        </div>
        <div className="strategy-meta">
          <span>{rows.length} ranked</span>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Ticker</th>
              <th>Price</th>
              <th>Wave A</th>
              <th>Wave B</th>
              <th>Wave C</th>
              <th>Target</th>
              <th>Timing</th>
              <th>Risk</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="empty-row" colSpan="10">{emptyMessage}</td>
              </tr>
            ) : rows.map((row) => (
              <tr key={`${title}-${row.ticker}`}>
                <td>{row.rank}</td>
                <td>
                  <strong>{row.ticker}</strong>
                  <small>{row.name || row.ticker}</small>
                </td>
                <td>
                  ${fmt(row.price, 2)}
                  <small>RSI {fmt(row.daily_rsi, 1)}</small>
                </td>
                <td>
                  {fmt(row.wave_a_pct, 1)}%
                  <small>{row.wave_a_start?.date || "-"} to {row.wave_a_end?.date || "-"}</small>
                </td>
                <td>
                  {fmt(row.wave_b_retrace, 1)}%
                  <small>B end {row.wave_b_end?.date || "-"}</small>
                </td>
                <td>
                  {fmt(row.wave_c_progress, 1)}%
                  <small>Vol {fmt(row.volume_ratio_5d_vs_20d, 2)}x</small>
                </td>
                <td>
                  ${fmt(row.target_price, 2)}
                  <small>stretch ${fmt(row.stretch_target_price, 2)}</small>
                </td>
                <td>
                  {row.expected_c_days_remaining ?? "-"}d
                  <small>
                    {row.expected_completion_date || "-"}
                    {row.expected_c_days_range ? ` | ${row.expected_c_days_range.min}-${row.expected_c_days_range.max}d` : ""}
                  </small>
                </td>
                <td>
                  RR {fmt(row.reward_risk, 2)}
                  <small>invalid ${fmt(row.invalidation_price, 2)}</small>
                </td>
                <td className="score">{fmt(row.score, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function App() {
  const [savedParams, setSavedParams] = useState(BASE_DEFAULTS);
  const [params, setParams] = useState(BASE_DEFAULTS);
  const [status, setStatus] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKeyInput, setShowKeyInput] = useState(false);
  const [showUniverse, setShowUniverse] = useState(false);
  const [paramsOpen, setParamsOpen] = useState(true);

  const modified = useMemo(() => changedCount(params, savedParams), [params, savedParams]);
  const customDefaults = useMemo(() => changedCount(savedParams, BASE_DEFAULTS), [savedParams]);
  const withKey = apiKey ? { "X-Api-Key": apiKey } : {};

  const handleAuthError = useCallback((err) => {
    if (err?.status === 401) {
      setShowKeyInput(true);
      setError("Enter a valid SCAN_API_KEY to run protected actions.");
      return true;
    }
    return false;
  }, []);

  const loadDefaults = useCallback(async () => {
    const json = await fetchJson("/defaults");
    setSavedParams(json.defaults);
    setParams((current) => (changedCount(current, BASE_DEFAULTS) === 0 ? json.defaults : current));
  }, []);

  const loadStatus = useCallback(async () => {
    const json = await fetchJson("/status");
    setStatus(json);
    return json;
  }, []);

  const loadResults = useCallback(async () => {
    const json = await fetchJson("/results");
    if (json.status === "ok") {
      setData(json);
    }
    return json;
  }, []);

  useEffect(() => {
    Promise.all([loadDefaults(), loadStatus(), loadResults()]).catch((err) => setError(err.message));
  }, [loadDefaults, loadResults, loadStatus]);

  useEffect(() => {
    if (!status?.is_scanning && !status?.is_refreshing) return undefined;
    const id = setInterval(async () => {
      try {
        const latest = await loadStatus();
        if (latest?.is_scanning || latest?.has_data) {
          await loadResults();
        }
      } catch (err) {
        setError(err.message);
      }
    }, 4000);
    return () => clearInterval(id);
  }, [status?.is_scanning, status?.is_refreshing, loadResults, loadStatus]);

  const updateParam = (key, value) => setParams((current) => ({ ...current, [key]: value }));

  const runScan = async () => {
    setError("");
    try {
      await fetchJson("/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...withKey },
        body: JSON.stringify(params),
      });
      await loadStatus();
    } catch (err) {
      if (!handleAuthError(err)) setError(err.message);
    }
  };

  const cancelScan = async () => {
    setError("");
    try {
      await fetchJson("/cancel-scan", { method: "POST", headers: withKey });
      await loadStatus();
    } catch (err) {
      if (!handleAuthError(err)) setError(err.message);
    }
  };

  const refreshUniverse = async () => {
    setError("");
    try {
      await fetchJson("/refresh-universe", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...withKey },
        body: JSON.stringify(params),
      });
      await loadStatus();
    } catch (err) {
      if (!handleAuthError(err)) setError(err.message);
    }
  };

  const saveDefaults = async () => {
    setError("");
    try {
      const json = await fetchJson("/defaults", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...withKey },
        body: JSON.stringify(params),
      });
      setSavedParams(json.defaults);
    } catch (err) {
      if (!handleAuthError(err)) setError(err.message);
    }
  };

  const totalRanked = (data?.bullish_candidates?.length || 0) + (data?.bearish_candidates?.length || 0);

  return (
    <div className="app-shell">
      <style>{`
        *{box-sizing:border-box}
        body{margin:0;font-family:ui-sans-serif,system-ui,sans-serif;background:${COLORS.paper};color:${COLORS.ink}}
        .app-shell{min-height:100vh;background:radial-gradient(circle at top right,#efe4d2,transparent 24%),linear-gradient(180deg,#f8f3eb 0%,#f1e9dd 100%)}
        .frame{max-width:1320px;margin:0 auto;padding:24px 20px 40px}
        .topbar,.hero,.panel{background:${COLORS.panel};border:1px solid ${COLORS.line};border-radius:22px;box-shadow:0 10px 30px rgba(43,32,17,.05)}
        .topbar{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;gap:16px;flex-wrap:wrap}
        .brand strong{display:block;font:700 30px Georgia,serif}
        .brand span{color:${COLORS.muted};font-size:12px;letter-spacing:.12em;text-transform:uppercase}
        .actions,.panel-actions,.summary-grid,.research-grid,.field-body,.field-head,.progress-head{display:flex;align-items:center}
        .actions,.panel-actions{gap:10px;flex-wrap:wrap}
        button{font:600 12px/1 ui-monospace,monospace;border-radius:12px;padding:12px 16px;border:1px solid ${COLORS.line};background:white;cursor:pointer}
        button.primary{background:${COLORS.ink};color:white;border-color:${COLORS.ink}}
        button.alert{background:#fff4f1;color:${COLORS.bearish};border-color:#edc5bc}
        .hero{margin-top:18px;padding:24px}
        .hero-grid{display:grid;grid-template-columns:1.25fr .95fr;gap:16px}
        .hero h1{margin:0 0 8px;font:700 40px/1.03 Georgia,serif;max-width:12ch}
        .muted{color:${COLORS.muted}}
        .summary-grid,.research-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}
        .stat,.research-card{padding:16px;border:1px solid ${COLORS.line};border-radius:16px;background:#fff}
        .stat strong,.research-card strong{display:block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:${COLORS.faint}}
        .stat span{display:block;margin-top:10px;font:700 28px/1 ui-monospace,monospace}
        .stat small,.research-card small,.strategy-meta,.table-wrap small,.progress-copy,.field-head em,.footer-note{color:${COLORS.muted}}
        .panel{margin-top:18px;padding:18px}
        .panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
        .panel-head h2{margin:0;font:700 24px Georgia,serif}
        .progress{min-width:290px;flex:1;background:#fff;border:1px solid ${COLORS.line};border-radius:14px;padding:12px}
        .progress-track{height:10px;background:#ece1d0;border-radius:999px;overflow:hidden;margin:8px 0}
        .progress-fill{height:100%;border-radius:999px;transition:width .35s ease}
        .progress-head{justify-content:space-between;font:600 12px ui-monospace,monospace}
        .progress-copy{font-size:11px;line-height:1.35}
        .settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:16px}
        .group{border:1px solid ${COLORS.line};border-radius:18px;padding:14px;background:#fff}
        .group h3{margin:0 0 12px;font:700 16px Georgia,serif}
        .field,.toggle{display:block;width:100%;margin:0 0 10px;border:1px solid ${COLORS.line};border-radius:14px;background:#fbf7f0;padding:12px}
        .field.modified{border-color:#d4a76f}
        .field-head{justify-content:space-between;margin-bottom:8px;font-size:11px;text-transform:uppercase;letter-spacing:.08em}
        .field-body{gap:10px}
        .field input[type=range]{flex:1;accent-color:${COLORS.ocean}}
        .field input[type=number]{width:94px;padding:8px;border:1px solid ${COLORS.line};border-radius:10px;font:600 13px ui-monospace,monospace;background:white}
        .toggle{display:flex;justify-content:space-between;align-items:center}
        .toggle.on{background:#e3f0ee;border-color:#9ec5bb}
        .banner{margin-top:14px;padding:14px 16px;border-radius:16px;border:1px solid ${COLORS.alertLine};background:${COLORS.alert}}
        .banner-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:10px}
        .banner input{flex:1;min-width:220px;padding:10px 12px;border:1px solid ${COLORS.line};border-radius:12px}
        .candidates{padding:0;overflow:hidden}
        .strategy-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;padding:16px 18px;border-bottom:1px solid ${COLORS.line};flex-wrap:wrap}
        .strategy-head h3{display:inline-block;margin:0 0 0 10px;font:700 22px Georgia,serif}
        .tag{display:inline-block;padding:6px 10px;border:1px solid;border-radius:999px;font:700 11px ui-monospace,monospace;letter-spacing:.08em;background:#fff}
        .strategy-meta{display:flex;gap:10px;flex-wrap:wrap;color:${COLORS.muted};font-size:12px}
        .table-wrap{overflow:auto}
        table{width:100%;border-collapse:collapse;min-width:1240px}
        th,td{padding:12px 10px;text-align:left;border-bottom:1px solid #efe6d8;vertical-align:top}
        th{font:600 11px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:${COLORS.faint};background:#fbf8f2}
        td strong,td small{display:block}
        .score{font:700 16px ui-monospace,monospace}
        .empty-row{text-align:center;color:${COLORS.muted};padding:18px}
        .footer-note{margin-top:18px;font-size:12px}
        @media (max-width:980px){.hero-grid,.summary-grid,.research-grid{grid-template-columns:1fr 1fr}}
        @media (max-width:720px){.hero-grid,.summary-grid,.research-grid{grid-template-columns:1fr}.topbar{align-items:flex-start}}
      `}</style>

      <div className="frame">
        <div className="topbar">
          <div className="brand">
            <strong>Elliott Wave Radar</strong>
            <span>daily-chart wave b to wave c scanner</span>
          </div>
          <div className="actions">
            <button className="alert" onClick={cancelScan} disabled={!status?.is_scanning}>Cancel Scan</button>
            <button className="primary" onClick={runScan} disabled={status?.is_scanning}>Run Scan</button>
          </div>
        </div>

        <div className="hero">
          <div className="hero-grid">
            <div>
              <h1>Find likely early Wave C setups on the daily chart.</h1>
              <p className="muted">
                This standalone scanner looks for a completed Wave B retracement, checks that Wave C has only started,
                and ranks the cleanest bullish and bearish structures with price targets and time estimates.
              </p>
            </div>
            <div className="panel" style={{ marginTop: 0, padding: 14 }}>
              <div className="panel-actions">
                <button onClick={refreshUniverse} disabled={status?.is_refreshing}>Refresh Universe</button>
                <button onClick={() => setShowUniverse(true)}>View Universe</button>
                <button onClick={() => setParams(savedParams)} disabled={modified === 0}>Revert</button>
                <button onClick={() => setParams(BASE_DEFAULTS)}>Factory Reset</button>
                <button className="primary" onClick={saveDefaults}>Save as Default</button>
              </div>
              {status?.is_refreshing && <ProgressBar title="Universe refresh" progress={status.refresh_progress} color={COLORS.ocean} />}
            </div>
          </div>

          {showKeyInput && (
            <div className="banner">
              <strong>Admin key required</strong>
              <div className="muted">Enter your SCAN_API_KEY once. Nothing will auto-run when you save it.</div>
              <div className="banner-row">
                <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="SCAN_API_KEY" />
                <button className="primary" onClick={() => { setShowKeyInput(false); setError(""); }}>Use Key</button>
              </div>
            </div>
          )}

          {error && <div className="banner">{error}</div>}

          <div className="summary-grid">
            <div className="stat"><strong>Universe</strong><span>{status?.universe_size || data?.universe_size || "-"}</span><small>{status?.universe_cache?.count || 0} cached tickers</small></div>
            <div className="stat"><strong>Ranked</strong><span>{totalRanked}</span><small>{data?.bullish_candidates?.length || 0} bullish / {data?.bearish_candidates?.length || 0} bearish</small></div>
            <div className="stat"><strong>Last Scan</strong><span>{data?.scan_time ? new Date(data.scan_time).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }) : "-"}</span><small>{data?.scanned || 0} tickers processed</small></div>
            <div className="stat"><strong>Defaults</strong><span>{customDefaults ? "Custom" : "Factory"}</span><small>{modified} unsaved changes</small></div>
          </div>

          {status?.is_scanning && <ProgressBar title="Scan progress" progress={status.scan_progress} color={COLORS.neutral} />}

          <div className="research-grid">
            <div className="research-card">
              <strong>Price Logic</strong>
              <small>Primary target assumes Wave C travels about the same distance as Wave A. Stretch target uses 1.618 x Wave A.</small>
            </div>
            <div className="research-card">
              <strong>Time Logic</strong>
              <small>Expected completion time centers on Wave A duration, with a wider Fibonacci-style window from 0.618x to 1.618x.</small>
            </div>
            <div className="research-card">
              <strong>Wave B Filter</strong>
              <small>Best candidates usually retrace a meaningful share of Wave A without fully invalidating the prior impulse.</small>
            </div>
            <div className="research-card">
              <strong>Momentum Filter</strong>
              <small>Daily RSI and EMA alignment help avoid late-stage or already-exhausted moves.</small>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <div>
              <h2>Scanner Parameters</h2>
              <div className="muted">This app is independent of the options scanner. Saved defaults persist in this Elliott scanner backend only.</div>
            </div>
            <button onClick={() => setParamsOpen((open) => !open)}>{paramsOpen ? "Collapse" : "Expand"}</button>
          </div>
          {paramsOpen && (
            <div className="settings-grid">
              {GROUPS.map((group) => (
                <div className="group" key={group.label}>
                  <h3>{group.label}</h3>
                  {group.fields.map((spec) => (
                    <Field
                      key={spec[0]}
                      spec={spec}
                      value={params[spec[0]]}
                      savedValue={savedParams[spec[0]]}
                      onChange={updateParam}
                    />
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        <CandidateTable
          title="Bullish Wave C Candidates"
          tag="BULLISH"
          color={COLORS.bullish}
          rows={data?.bullish_candidates || []}
          emptyMessage="No bullish Wave C candidates yet."
        />

        <CandidateTable
          title="Bearish Wave C Candidates"
          tag="BEARISH"
          color={COLORS.bearish}
          rows={data?.bearish_candidates || []}
          emptyMessage="No bearish Wave C candidates yet."
        />

        <div className="footer-note">
          This scanner uses heuristic Elliott-wave pattern recognition rather than a literal discretionary wave count. Price targets and completion windows are probabilistic estimates, not guarantees.
        </div>
      </div>

      <UniverseModal isOpen={showUniverse} onClose={() => setShowUniverse(false)} apiUrl={API_URL} />
    </div>
  );
}
