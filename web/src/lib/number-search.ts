/** Inventory selection stays internal; purchase must use the source of the displayed result. */
export interface AvailableNumber {
  number: string;
  friendly: string;
  locality: string;
  region: string;
  carrier: string;
}

export async function searchNumberInventory(
  carriers: string[],
  search: (carrier: string) => Promise<{ numbers: Omit<AvailableNumber, "carrier">[] }>,
): Promise<AvailableNumber[]> {
  let failed = false;
  for (const carrier of [...new Set(carriers)]) {
    try {
      const result = await search(carrier);
      if (result.numbers.length) return result.numbers.map((n) => ({ ...n, carrier }));
    } catch {
      failed = true;
    }
  }
  if (failed || !carriers.length) throw new Error("Couldn't search numbers right now. Please try again.");
  return [];
}
