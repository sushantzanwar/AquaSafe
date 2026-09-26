export function PriorityBadge({ score }: { score: number }) {
  const tier =
    score >= 80 ? "Critical" : score >= 50 ? "Elevated" : "Routine";
  const color =
    score >= 80
      ? "text-red-300 border-red-700"
      : score >= 50
      ? "text-amber-300 border-amber-700"
      : "text-emerald-300 border-emerald-700";

  return (
    <div
      className={`inline-flex flex-col items-center rounded-xl border px-4 py-2 ${color}`}
    >
      <span className="text-xs uppercase tracking-wide opacity-70">
        Priority
      </span>
      <span className="text-2xl font-bold">{score}</span>
      <span className="text-xs opacity-70">{tier}</span>
    </div>
  );
}
