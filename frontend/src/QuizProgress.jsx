import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export default function QuizProgress({ items, label }) {
  return <div className="chart" aria-label={label} role="group">
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <BarChart data={items} margin={{ top: 8, right: 10, bottom: 2, left: 0 }}>
        <CartesianGrid vertical={false} stroke="#d8d0c7" />
        <XAxis dataKey="label" tick={false} />
        <YAxis width={36} domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
        <Tooltip formatter={value => [value + '%', 'Marks earned']} />
        <Bar dataKey="percentage" fill="#0f3f49" maxBarSize={45} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  </div>
}
