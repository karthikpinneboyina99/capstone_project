import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'

interface DataPoint {
  date: string
  value: number
  baseline?: number
}

export default function EquityCurveChart({ data }: { data: DataPoint[] }) {
  if (!data.length) {
    return (
      <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
        No data yet
      </div>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
        <YAxis
          tick={{ fill: '#94a3b8', fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
        />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
          labelStyle={{ color: '#cbd5e1' }}
          formatter={(v: number) => [`$${v.toLocaleString()}`, 'Portfolio']}
        />
        <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} />
        {data[0]?.baseline !== undefined && (
          <Line
            type="monotone"
            dataKey="baseline"
            stroke="#6366f1"
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="4 4"
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}
