'use client';

type SparklineProps = {
  data: number[];
  isUp: boolean;
};

export function Sparkline({ data, isUp }: SparklineProps) {
  if (data.length < 2) return <div className="w-16 h-5" />;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 64;
  const h = 20;

  const pts = data
    .map(
      (v, i) =>
        `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`
    )
    .join(' ');

  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline
        points={pts}
        fill="none"
        stroke={isUp ? '#3fb950' : '#f85149'}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
