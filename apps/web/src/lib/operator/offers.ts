export function decimalToMinorUnits(raw: string): number | null {
  const value = raw.trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  const minor = BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0"));
  if (
    minor > BigInt("1000000000000000") ||
    minor > BigInt(Number.MAX_SAFE_INTEGER)
  )
    return null;
  return Number(minor);
}

export function minorUnitsToDecimal(value: number): string {
  return `${Math.floor(value / 100)}.${String(value % 100).padStart(2, "0")}`;
}

export function formatOperatorMoney(value: number, currency: string): string {
  return new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(
    value / 100,
  );
}
