import { LeaderboardBars } from '@/components/ui/leaderboard-bars'

export default function LeaderboardBarsDemo() {
  return (
    <LeaderboardBars
      rowLabel="configuration"
      barLabel="pass@1"
      columns={['cost', 'tokens', 'min']}
      rows={[
        {
          label: 'Opus 4.8',
          sub: 'Claude Code',
          value: 78.7,
          std: 6.1,
          metrics: ['$3.12', '33k', '13'],
          color: '#E8734A',
        },
        {
          label: 'Sonnet 5',
          sub: 'Claude Code',
          value: 74.7,
          std: 2.3,
          metrics: ['$2.42', '29k', '13'],
          color: '#E8734A',
        },
        {
          label: 'GPT-5.5',
          sub: 'Codex',
          value: 66.7,
          std: 4.6,
          metrics: ['$2.34', '16k', '12'],
          color: '#10A37F',
        },
        {
          label: 'Haiku 4.5',
          sub: 'Claude Code',
          value: 53.3,
          std: 4.6,
          metrics: ['$0.57', '18k', '10'],
          color: '#E8734A',
        },
        {
          label: 'Fable 5',
          value: 85,
          valueLabel: '85% · 17/20',
          offside: true,
          offsideTag: 'OFF THE BOARD',
        },
      ]}
    />
  )
}
