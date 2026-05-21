export default function AIAnalysis({ summary, stocks }) {
  const gainers = stocks.filter(s => s.fiveDayPct > 0);
  const losers = stocks.filter(s => s.fiveDayPct < 0);
  const signals = stocks.map(s => s.analysis?.signal).filter(Boolean);
  const buySignals = signals.filter(s => s.includes('buy')).length;
  const sellSignals = signals.filter(s => s.includes('sell')).length;

  const signalBars = [
    { label: '買入信號', count: buySignals, color: 'bg-blue-500' },
    { label: '賣出信號', count: sellSignals, color: 'bg-orange-500' },
    { label: '上漲', count: gainers.length, color: 'bg-green-500' },
    { label: '下跌', count: losers.length, color: 'bg-red-500' },
  ];

  return (
    <section className="space-y-4">
      {/* AI Summary Banner */}
      <div className="bg-gradient-to-r from-blue-900/50 to-slate-800 rounded-xl p-6 border border-blue-800/50">
        <div className="flex items-start gap-3">
          <div className="text-3xl">🤖</div>
          <div>
            <h2 className="font-bold text-blue-300 mb-2">AI 市場分析</h2>
            <p className="text-slate-200 text-sm leading-relaxed">{summary}</p>
          </div>
        </div>
      </div>

      {/* Signal Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {signalBars.map(({ label, count, color }) => (
          <div key={label} className="bg-slate-800 rounded-lg p-4 border border-slate-700 text-center">
            <div className="text-2xl font-bold text-white">{count}</div>
            <div className="text-xs text-slate-400 mt-1">{label}</div>
            <div className="mt-2 h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <div
                className={`h-full ${color} rounded-full transition-all`}
                style={{ width: `${Math.round((count / (stocks.length || 1)) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Top Gainers / Losers */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Top Gainers */}
        <div className="card">
          <h3 className="font-semibold text-green-400 mb-3 flex items-center gap-2">
            <span>🏆</span> 五日表現最佳
          </h3>
          <div className="space-y-2">
            {[...stocks]
              .sort((a, b) => b.fiveDayPct - a.fiveDayPct)
              .slice(0, 5)
              .map((s, i) => (
                <div key={s.code} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-500 w-4 text-center">{i + 1}</span>
                    <span className="font-medium text-slate-200">{s.name}</span>
                    <span className="text-slate-500 font-mono text-xs">{s.code}</span>
                  </div>
                  <span className="text-green-400 font-bold">▲ {s.fiveDayPct.toFixed(2)}%</span>
                </div>
              ))}
          </div>
        </div>

        {/* Top Losers */}
        <div className="card">
          <h3 className="font-semibold text-red-400 mb-3 flex items-center gap-2">
            <span>📉</span> 五日表現最弱
          </h3>
          <div className="space-y-2">
            {[...stocks]
              .sort((a, b) => a.fiveDayPct - b.fiveDayPct)
              .slice(0, 5)
              .map((s, i) => (
                <div key={s.code} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-500 w-4 text-center">{i + 1}</span>
                    <span className="font-medium text-slate-200">{s.name}</span>
                    <span className="text-slate-500 font-mono text-xs">{s.code}</span>
                  </div>
                  <span className="text-red-400 font-bold">▼ {Math.abs(s.fiveDayPct).toFixed(2)}%</span>
                </div>
              ))}
          </div>
        </div>
      </div>
    </section>
  );
}
