/** "1,234 credits" — balances are shown in credits only (credits aren't cash). */
export function amount(credits: number): string {
  return `${credits.toLocaleString(undefined, { maximumFractionDigits: 2 })} credit${credits === 1 ? "" : "s"}`;
}
