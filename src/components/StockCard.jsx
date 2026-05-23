import MiniChart from './MiniChart.jsx';

const SIGNAL_COLORS = {
  'strong buy': { bg: 'bg-blue-900/40', text: 'text-blue-400', label: '💎 強烈買入' },
  'buy':        { bg: 'bg-blue-900/30', text: 'text-blue-300', label: '✅ 買入' },
  'hold':       { bg: 'bg-slate-800',  text: 'text-slate-300', label: '⏸ 持有' },
  'watch':      { bg: 'bg-yellow-900/30', text: 'text-yellow-400', label: '👁 觀望' },
  'sell':       { bg: 'bg-orange-900/30', text: 'text-orange-400', label: '⚠️ 賣出' },
  'strong sell':{ bg: 'bg-red-900/40', text: 'text-red-400', label: '🔴 強烈賣出' },
  'neutral':    { bg: 'bg-slate-800',  text: 'text-slate-400', label: '➖ 中性' },
};
const SIGNAL_ORDER = ['strong buy','buy','hold','watch','sell','strong sell','neutral'];

function getSignalStyle(signal) {
  return SIGNAL_COLORS[signal] || SIGNAL_COLORS['neutral'];
}

function isAiRow(dateStr) {
  return String(dateStr).includes('_PRED') || String(dateStr).includes('PRED');
}

export default function StockCard({ stock, prediction }) {
  const { code, name, symbol, prices, fiveDayPct, analysis } = stock;
  const isUp     = fiveDayPct >= 0;
  const pctColor = isUp ? 'text-red-400' : 'text-green-400';
  const arrow    = isUp ? '▲' : '▼';
  const sigStyle = getSignalStyle(analysis?.signal || 'neutral');
  const trendIcon = analysis?.trend === 'uptrend' ? '↗' : analysis?.trend === 'downtrend' ? '↘' : '→';
  const volIcon   = analysis?.volumeSignal === 'volume surge' ? '🔥' : analysis?.volumeSignal === 'volume decline' ? '📉' : '➡';

  // combined_data: [0-9] = 10 historical days, [10-14] = 5 AI future days
  const hasAi   = prediction?.has_ai && Array.isArray(prediction.combined_data);
  const histRows  = hasAi ? prediction.combined_data.slice(0, 10) : (prices || []);
  const predRows  = hasAi ? prediction.combined_data.slice(10, 15) : [];
  const chartRows = hasAi ? prediction.combined_data : (prices || []);

  return (
    <div className="card space-y-3">

      {/* ── Card Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-slate-400">{code}</span>
            <span className={`badge ${isUp ? 'badge-up' : 'badge-down'}`}>
              {arrow} {Math.abs(fiveDayPct).toFixed(2)}%
            </span>
            {hasAi && <span className="badge bg-purple-900/50 text-purple-300 text-xs">🔮 AI</span>}
          </div>
          <h3 className="font-bold text-white text-base mt-0.5">
            {prediction?.name || name}
          </h3>
          <p className="text-xs text-slate-500">{symbol}</p>
        </div>
        <div className={`badge ${sigStyle.bg} ${sigStyle.text} text-xs`}>
          {sigStyle.label}
        </div>
      </div>

      {/* ── Candlestick Chart (15 bars: 10 hist + 5 AI) ── */}
      {chartRows.length > 0 && (
        <MiniChart prices={chartRows} hasAi={hasAi} histCount={10} />
      )}

      {/* ── Last Price + Stats ── */}
      {prices?.length > 0 && (
        <div className="flex items-baseline justify-between border-t border-slate-700 pt-2">
          <div>
            <span className="text-2xl font-bold text-white">
              {prices[prices.length - 1].close.toFixed(2)}
            </span>
            <span className="text-sm text-slate-400 ml-1">HKD</span>
          </div>
          <div className="text-right text-xs text-slate-400 space-y-0.5">
            <p>5日高 {Math.max(...prices.map(p => p.high)).toFixed(2)}</p>
            <p>5日低 {Math.min(...prices.map(p => p.low)).toFixed(2)}</p>
          </div>
        </div>
      )}

      {/* ── Stats Row ── */}
      <div className="flex items-center justify-between text-xs text-slate-400">
        <div className="flex items-center gap-3">
          <span>趨勢 {trendIcon}</span>
          <span>量 {volIcon}</span>
        </div>
        {analysis?.support > 0 && <span className="text-green-400">撐 {analysis.support.toFixed(2)}</span>}
        {analysis?.resistance > 0 && <span className="text-red-400">壓 {analysis.resistance.toFixed(2)}</span>}
      </div>

      {/* ── AI Summary ── */}
      {analysis?.summary && (
        <div className="bg-slate-900/60 rounded-lg p-3 text-xs text-slate-300 leading-relaxed">
          🤖 {analysis.summary}
        </div>
      )}

      {/* ── Historical Price Table ── */}
      {histRows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-700">
                <th className="text-left py-1">日期</th>
                <th className="text-right">開</th>
                <th className="text-right">高</th>
                <th className="text-right">低</th>
                <th className="text-right">收</th>
                <th className="text-right">量(M)</th>
              </tr>
            </thead>
            <tbody>
              {histRows.map((p, i) => (
                <tr key={p.date} className={`border-b border-slate-800 ${i === histRows.length - 1 ? 'bg-slate-700/30' : ''}`}>
                  <td className="py-1 text-slate-400">{p.dateShort || p.date}</td>
                  <td className="text-right text-slate-300">{parseFloat(p.open).toFixed(2)}</td>
                  <td className="text-right text-red-400">{parseFloat(p.high).toFixed(2)}</td>
                  <td className="text-right text-green-400">{parseFloat(p.low).toFixed(2)}</td>
                  <td className={`text-right font-medium ${parseFloat(p.close) >= parseFloat(p.open) ? 'text-green-400' : 'text-red-400'}`}>
                    {parseFloat(p.close).toFixed(2)}
                  </td>
                  <td className="text-right text-slate-400">{p.volumeM}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── AI Prediction Matrix ── */}
      {hasAi && predRows.length > 0 && (
        <div className="ai-prediction-matrix border border-purple-700/60 rounded-lg overflow-hidden">
          <div className="bg-purple-900/30 px-3 py-1.5 flex items-center gap-2 border-b border-purple-700/40">
            <span className="text-purple-300 text-xs font-semibold">🔮 AI 預測（未來5日）</span>
            <span className="text-xs text-slate-500">OpenRouter owl-alpha</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-purple-400/70 border-b border-purple-700/30">
                <th className="text-left py-1 px-2">日期</th>
                <th className="text-right py-1 px-1">開</th>
                <th className="text-right py-1 px-1">高</th>
                <th className="text-right py-1 px-1">低</th>
                <th className="text-right py-1 px-1">收</th>
                <th className="text-right py-1 px-1">量(M)</th>
              </tr>
            </thead>
            <tbody>
              {predRows.map((p, i) => {
                const isUpPred = parseFloat(p.close) >= parseFloat(p.open);
                return (
                  <tr key={`pred-${i}`} className="opacity-80 hover:opacity-100 transition-opacity border-b border-purple-700/20 last:border-0">
                    <td className="py-1 px-2 text-purple-300">
                      {isAiRow(p.date) ? p.date : `${p.date}_PRED`}
                    </td>
                    <td className="text-right py-1 px-1 text-slate-300">{parseFloat(p.open).toFixed(2)}</td>
                    <td className="text-right py-1 px-1 text-red-400">{parseFloat(p.high).toFixed(2)}</td>
                    <td className="text-right py-1 px-1 text-green-400">{parseFloat(p.low).toFixed(2)}</td>
                    <td className={`text-right py-1 px-1 font-medium ${isUpPred ? 'text-green-400' : 'text-red-400'}`}>
                      {parseFloat(p.close).toFixed(2)}
                    </td>
                    <td className="text-right py-1 px-1 text-slate-400">{p.volumeM}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!hasAi && (
        <div className="text-center text-xs text-slate-600 py-2">
          🔮 AI 預測（請設定 OPENROUTER_API_KEY）
        </div>
      )}

    </div>
  );
}
