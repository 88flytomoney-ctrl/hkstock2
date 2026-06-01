import { useState, useEffect } from 'react';
import StockCard from './components/StockCard.jsx';

const PREDICT_URL  = '/hkstock2/data/predictions.json';
const MANIFEST_URL = '/hkstock2/data/history/manifest.json';

// Append HKT suffix — stored generatedAt values are already in HK local time
function toHKTime(utcStr) {
  if (!utcStr) return '';
  try {
    return utcStr.trim() + ' HKT';
  } catch {
    return utcStr;
  }
}

// ── Transform predictions.json structure into {stocks[], stockCount} ──────────
function transformPredictions(predData) {
  // Handle both predictions.json (object) and history.json (array) formats
  let stocksMap = {};
  
  if (Array.isArray(predData.stocks)) {
    // History format: stocks is an array of { code, symbol, name, prices }
    // prices is already the actual (non-predicted) data
    predData.stocks.forEach(s => {
      stocksMap[s.code] = {
        name: s.name,
        symbol: s.symbol,
        combined_data: s.prices || [] // Treat prices as combined_data (all actuals)
      };
    });
  } else {
    // Predictions format: stocks is an object of { code: { combined_data } }
    stocksMap = predData.stocks || {};
  }

  const stocksList = [];
  for (const code of Object.keys(stocksMap)) {
    const s = stocksMap[code];
    const combined = s.combined_data || [];
    const actuals = combined.filter(r => !r.is_predicted);
    // Compute 5-day change
    let fiveDayPct = 0;
    if (actuals.length >= 2) {
      fiveDayPct = ((actuals[actuals.length - 1].close - actuals[0].close) / actuals[0].close) * 100;
    }
    stocksList.push({
      code,
      name: s.name,
      symbol: s.symbol,
      prices: actuals,
      fiveDayPct,
      analysis: {},
    });
  }
  return {
    stocks: stocksList,
    stockCount: stocksList.length,
    generatedAt: predData.generatedAt || new Date().toLocaleString('zh-TW', { timeZone: 'Asia/Hong_Kong' }),
  };
}

// ── Style helper for recommendation badges ────────────────────────────────────
function getIndicatorStyles(rec) {
  if (rec === "買入") return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
  if (rec === "賣出") return "bg-rose-500/10 text-rose-400 border-rose-500/20";
  return "bg-slate-500/10 text-slate-400 border-slate-500/20";
}

function App() {
  const [data,         setData]         = useState(null);
  const [predictionsDB, setPredictionsDB] = useState(null);   // {stocks: {...}, indices: {...}}
  const [loading,      setLoading]      = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error,        setError]        = useState(null);
  const [lastUpdated,  setLastUpdated]  = useState('');
  const [historyDates, setHistoryDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState('');

  // ── Load data + AI predictions ───────────────────────────────────────────
  useEffect(() => {
    fetch(PREDICT_URL)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(p => {
        setPredictionsDB(p);
        const stockData = transformPredictions(p);
        setData(stockData);
        setLastUpdated(toHKTime(stockData.generatedAt));
        setLoading(false);
      })
      .catch(e => { setError(e.message); setLoading(false); });
  }, []);

  // ── Load history dates ───────────────────────────────────────────────────
  useEffect(() => {
    fetch(MANIFEST_URL)
      .then(r => r.ok ? r.json() : [])
      .then(dates => setHistoryDates(dates))
      .catch(() => setHistoryDates([]));
  }, []);

  // ── Load selected history date ────────────────────────────────────────────
  useEffect(() => {
    if (!selectedDate) {
      fetch(PREDICT_URL)
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then(p => {
          setPredictionsDB(p);
          const stockData = transformPredictions(p);
          setData(stockData);
          setLastUpdated(toHKTime(stockData.generatedAt));
          setError(null);
          setLoadingHistory(false);
        })
        .catch(e => { setError(e.message); setLoadingHistory(false); });
      return;
    }
    setLoadingHistory(true);
    fetch(`/hkstock2/data/history/${selectedDate}.json`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => {
        setPredictionsDB(d);
        const stockData = transformPredictions(d);
        setData(stockData);
        setLastUpdated(toHKTime(stockData.generatedAt));
        setError(null);
        setLoadingHistory(false);
      })
      .catch(e => { setError(e.message); setLoadingHistory(false); });
  }, [selectedDate]);

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin text-4xl mb-4">📊</div>
        <p className="text-slate-400">載入中...</p>
      </div>
    </div>
  );

  if (error) return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center card max-w-md">
        <div className="text-4xl mb-4">⚠️</div>
        <h2 className="text-lg font-bold text-red-400 mb-2">載入失敗</h2>
        <p className="text-slate-400 text-sm mb-4">{error}</p>
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm"
          onClick={() => window.location.reload()}>
          重試
        </button>
      </div>
    </div>
  );

  const stocksMap   = predictionsDB?.stocks  || {};
  const indicesData = predictionsDB?.indices || {};
  const aiCount     = Object.values(stocksMap).filter(p => p.has_ai).length;

  return (
    <div className="min-h-screen bg-slate-900">

      {/* ── Header ── */}
      <header className="bg-slate-800 border-b border-slate-700 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <svg className="w-8 h-8" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="6" fill="#1e40af"/>
              <path d="M6 22 L10 16 L14 19 L20 10 L26 14" stroke="#fbbf24" strokeWidth="2.5"
                strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="26" cy="14" r="2" fill="#fbbf24"/>
            </svg>
            <div>
              <h1 className="text-xl font-bold text-white">HK Stock 2 <span className="text-xs text-purple-400 ml-1">🤖 AI</span></h1>
              <p className="text-xs text-slate-400">ETNet Top {data?.stockCount || 10} · Yahoo 10日 · OpenRouter 5日預測</p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-xs text-slate-400">最後更新 (HKT)</p>
            <p className="text-sm font-medium text-slate-200">{lastUpdated}</p>
            {aiCount > 0 && <p className="text-xs text-purple-400 mt-1">🔮 AI: {aiCount} 檔</p>}
            {loadingHistory && <p className="text-xs text-blue-400 mt-1">載入歷史...</p>}
          </div>
          <select
            value={selectedDate}
            onChange={e => setSelectedDate(e.target.value)}
            className="ml-4 px-2 py-1 bg-slate-700 border border-slate-600 rounded text-sm text-slate-200 cursor-pointer"
          >
            <option value="">最新數據</option>
            {historyDates.length === 0 && <option value="" disabled>— 尚無歷史記錄 —</option>}
            {historyDates.map(d => <option key={d.file} value={d.file}>{d.display}</option>)}
          </select>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">

        {/* ── HK Market Indices Dashboard ── */}
        {Object.keys(indicesData).length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
              🌐 香港主要指數
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 bg-slate-950/40 border border-slate-800 rounded-xl">
              {Object.entries(indicesData).map(([ticker, idx]) => (
                <div key={ticker}
                  className="bg-slate-900 border border-slate-800/60 p-3 rounded-lg flex items-center justify-between">
                  <div>
                    <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                      {idx.name} ({ticker.replace('^', '')})
                    </span>
                    <div className="text-base font-black text-slate-100 mt-0.5">
                      {typeof idx.value === 'number' ? idx.value.toLocaleString() : idx.value}
                    </div>
                  </div>
                  <div className={`text-xs font-black px-2 py-0.5 rounded ${
                    idx.isPositive
                      ? 'bg-emerald-950/50 text-emerald-400'
                      : 'bg-rose-950/50 text-rose-400'
                  }`}>
                    {idx.isPositive ? '▲' : '▼'} {idx.change} ({idx.pct}%)
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── Stock Grid ── */}
        <section>
          <h2 className="text-lg font-semibold mb-4 text-slate-200">
            📈 個股行情（{data?.stockCount || 0} 檔）
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {data?.stocks?.map((stock) => {
              const pred    = stocksMap[stock.code];
              const rec    = pred?.recommendation || "持有";
              return (
                <StockCard
                  key={stock.code}
                  stock={stock}
                  prediction={pred}
                  recommendation={rec}
                />
              );
            })}
          </div>
        </section>

        <footer className="text-center text-xs text-slate-500 py-8">
          數據來源：ETNet + Yahoo Finance · AI 預測：OpenRouter owl-alpha · 僅供參考，不構成投資建議
        </footer>
      </main>
    </div>
  );
}

export default App;
