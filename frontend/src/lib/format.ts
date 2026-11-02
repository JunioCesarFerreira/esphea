const UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${UNITS[unit]}`;
}

export function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value !== 0 && (Math.abs(value) < 1e-3 || Math.abs(value) >= 1e6)) {
    return value.toExponential(2);
  }
  return Number(value.toPrecision(digits)).toString();
}

export function formatInteger(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${Math.round(seconds % 60)} s`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

export function secondsBetween(start: string | null, end: string | null): number | null {
  if (!start) return null;
  const finish = end ? new Date(end).getTime() : Date.now();
  return (finish - new Date(start).getTime()) / 1000;
}
