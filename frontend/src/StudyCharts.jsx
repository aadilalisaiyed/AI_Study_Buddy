import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const chartData = [12, 18, 15, 26, 24, 38, 33, 43, 41, 57, 53, 64, 57, 69].map((value, index) => ({ date: 'Oct ' + (15 + index), value }))
const mastery = [
  { name: 'Data Structures', value: 92, color: '#0f3f49' }, { name: 'Operating Systems', value: 84, color: '#7f0508' },
  { name: 'Database Systems', value: 78, color: '#b76366' }, { name: 'AI / ML', value: 76, color: '#be9c8c' },
]

export function ProgressChart() {
  return <div className="chart" role="group" aria-label="Illustrative study activity rises from 12 to 69 minutes between October 15 and 28."><ResponsiveContainer width="100%" height="100%" minWidth={0}><AreaChart data={chartData} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
    <CartesianGrid vertical={false} stroke="#d8d0c7" strokeDasharray="3 4" /><XAxis dataKey="date" minTickGap={28} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis width={28} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip formatter={value => [value + ' min', 'Study time']} /><Area dataKey="value" type="monotone" stroke="#7f0508" strokeWidth={2} fill="#e5c6c3" isAnimationActive={false} />
  </AreaChart></ResponsiveContainer></div>
}

export function MasteryChart() {
  return <div className="mastery"><div role="img" aria-label="Illustrative average subject mastery is 83 percent."><ResponsiveContainer width="100%" height={135}><PieChart><Pie data={mastery} dataKey="value" innerRadius={42} outerRadius={62} isAnimationActive={false}>{mastery.map(item => <Cell key={item.name} fill={item.color} />)}</Pie><Tooltip formatter={value => value + '%'} /></PieChart></ResponsiveContainer></div><ul>{mastery.map(item => <li key={item.name}>{item.name}<strong>{item.value}%</strong></li>)}</ul></div>
}
