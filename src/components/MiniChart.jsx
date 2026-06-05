import { ComposedChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, Cell } from 'recharts';

/* ── Candlestick shape ─────────────────────────────────────────────────────── */
function Candlestick({ x, y, width, height, payload, isPred, isUp }) {
  if (!payload) return null;
  const { open, high, low, close } = payload;
  const up    = isUp !== undefined ? isUp : close >= open;
  const color = up ? '#22c55e' : '#ef4444';
  const predColor = up ? '#a78bfa' : '#f472b6';   // purple/pink for AI bars

  // Calculate body boundaries correctly (not using ratio formula which breaks when high==low or close==low/high)
  const bodyTop    = up ? Math.min(open, close) : Math.max(open, close);
  const bodyBottom = up ? Math.max(open, close) : Math.min(open, close);
  
  // Normalize to chart scale
  const priceRange = high - low || 1;
  const normalizedTop = (high - bodyTop) / priceRange * height;
  const normalizedBottom = (high - bodyBottom) / priceRange * height;
  
  const rectY = y + normalizedTop;
  const rectHeight = Math.max(normalizedBottom - normalizedTop, 2);
  
  const cx         = x + width / 2;
  const fillColor  = isPred ? predColor : color;
  const strokeColor = isPred ? (up ? '#c084fc' : '#f9a8d4') : color;

  return (
    <g>
      {/* High-Low wick */}
      <line x1={cx} y1={y} x2={cx} y2={y + height}
        stroke={fillColor} strokeWidth={1} />
      {/* Open-Close body */}
      <rect
        x={x + 1}
        y={rectY}
        width={Math.max(width - 2, 4)}
        height={rectHeight}
        fill={fillColor}
        stroke={strokeColor}
        strokeWidth={isPred ? 2 : 1}
        strokeDasharray={isPred ? '3,1' : '0'}
        rx={1}
        opacity={isPred ? 0.85 : 1}
      />
    </g>
  );
}

/* ── MiniChart component ────────────────────────────────────────────────────── */
export default function MiniChart({ prices, hasAi, histCount = 5 }) {
  if (!prices || prices.length === 0) return null;

  const data = prices.map((p, i) => ({
    date:   p.dateShort || p.date,
    open:    parseFloat(p.open),
    high:    parseFloat(p.high),
    low:     parseFloat(p.low),
    close:   parseFloat(p.close),
    volume:  p.volumeM,
    isUp:    parseFloat(p.close) >= parseFloat(p.open),
    isPred:  hasAi && i >= histCount,
  }));

  const minPrice = Math.min(...data.map(d => d.low));
  const maxPrice = Math.max(...data.map(d => d.high));
  const padding  = (maxPrice - minPrice) * 0.1;

  return (
    <div className="h-24 relative">
      {/* AI zone label */}
      {hasAi && (
        <div className="absolute top-0 right-1 z-10 text-[9px] text-purple-400 leading-none">
          🔮 AI
        </div>
      )}
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <XAxis
            dataKey="date"
            tick={{ fill: '#64748b', fontSize: 9 }}
            axisLine={{ stroke: '#334155' }}
            tickLine={false}
          />
          <YAxis
            domain={[minPrice - padding, maxPrice + padding]}
            tick={{ fill: '#64748b', fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            width={45}
            tickFormatter={v => v.toFixed(0)}
          />
          <Tooltip
            contentStyle={{
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              fontSize: '11px',
              color: '#e2e8f0',
            }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(value, name) => {
              const labels = { open: '開', high: '高', low: '低', close: '收' };
              return [`${value.toFixed(2)}`, labels[name] || name];
            }}
          />
          <Bar dataKey="close" shape={<Candlestick />} isAnimationActive={false}>
            {data.map((entry, index) => (
              <Cell key={index} />
            ))}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex items-center gap-3 justify-end mt-0.5 px-1">
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-sm bg-green-500" />
          <span className="text-[9px] text-slate-500">實</span>
        </div>
        {hasAi && (
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-sm bg-purple-400" style={{ border: '1px dashed #c084fc' }} />
            <span className="text-[9px] text-slate-500">🔮AI</span>
          </div>
        )}
      </div>
    </div>
  );
}
