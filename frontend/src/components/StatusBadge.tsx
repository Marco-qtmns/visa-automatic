export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase().replaceAll(" ", "_");
  return <span className={`badge badge-${normalized}`}>{value.replaceAll("_", " ")}</span>;
}
