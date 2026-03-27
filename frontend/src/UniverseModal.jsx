import { useEffect, useMemo, useState } from "react";

export default function UniverseModal({ isOpen, onClose, apiUrl }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!isOpen) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    setError("");
    setSearch("");
    fetch(`${apiUrl}/universe`, { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        return res.json();
      })
      .then((json) => {
        setData(json);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [apiUrl, isOpen]);

  const filtered = useMemo(() => {
    if (!data?.tickers) return [];
    if (!search.trim()) return data.tickers;
    const q = search.trim().toUpperCase();
    return data.tickers.filter((ticker) => ticker.includes(q));
  }, [data, search]);

  if (!isOpen) return null;

  return (
    <>
      <style>{`
        .eum-backdrop{position:fixed;inset:0;background:rgba(14,12,16,.58);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;z-index:1000}
        .eum-card{width:min(920px,94vw);max-height:84vh;background:#fcfbf8;border:1px solid #d9d2c4;border-radius:24px;box-shadow:0 30px 80px rgba(0,0,0,.22);display:flex;flex-direction:column;overflow:hidden}
        .eum-head,.eum-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:18px 22px;border-bottom:1px solid #ece4d8}
        .eum-head h2{margin:0;font:700 28px Georgia,serif}
        .eum-close{padding:10px 14px;border-radius:12px;border:1px solid #d9d2c4;background:white;cursor:pointer}
        .eum-body{padding:18px 22px;overflow:auto}.eum-search{width:100%;padding:12px 14px;border-radius:14px;border:1px solid #d9d2c4;background:white;margin-bottom:16px}
        .eum-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(88px,1fr));gap:8px}.eum-chip{padding:10px 6px;border-radius:12px;border:1px solid #e9dfcf;background:white;text-align:center;font:700 13px ui-monospace,monospace;color:#2b251f}
        .eum-state{padding:42px 18px;text-align:center;color:#6b6258}.eum-foot{border-top:1px solid #ece4d8;border-bottom:none;background:#faf7f1}
      `}</style>
      <div className="eum-backdrop" onClick={(event) => event.target === event.currentTarget && onClose()}>
        <div className="eum-card">
          <div className="eum-head">
            <h2>Elliott Universe</h2>
            <button className="eum-close" onClick={onClose}>Close</button>
          </div>
          {loading ? (
            <div className="eum-state">Loading universe...</div>
          ) : error ? (
            <div className="eum-state">Failed to load universe: {error}</div>
          ) : (
            <>
              <div className="eum-body">
                <input className="eum-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search tickers..." />
                <div className="eum-grid">
                  {filtered.map((ticker) => <div className="eum-chip" key={ticker}>{ticker}</div>)}
                </div>
              </div>
              <div className="eum-foot">
                <span>{data?.count || 0} symbols</span>
                <span>{data?.source === "dynamic_cache" ? "Dynamic cache" : "Static fallback"}</span>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
