import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { parse } from "csv-parse/sync";
import { sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";
import { z } from "zod";
import { sales, type NewSale } from "../src/server/db/schema";

const volume = z
  .string()
  .regex(/^\d+$/)
  .transform(Number)
  .pipe(z.int().nonnegative().max(2_147_483_647));
const rowSchema = z.object({
  market_code: z.string().min(1),
  volume_2024: volume,
  volume_2025: volume,
  volume_2030: volume,
});

function parseSales(file: string, csv: string): NewSale[] {
  const group = file.match(/ - ([A-Z]\d+(?:_[A-Z]\d+)*)\.csv$/)?.[1];
  if (!group) throw new Error("Sales filename must end with ' - <model code>.csv'");
  const modelCode = group === "G60_G68" ? "G60" : group;
  const records = parse(csv, {
    bom: true,
    columns: true,
    trim: true,
    skip_empty_lines: true,
    info: true,
  }) as { record: Record<string, string>; info: { lines: number } }[];
  if (!records.length) throw new Error("Sales CSV contains no data rows");
  return records.map(({ record, info }) => {
    const parsed = rowSchema.safeParse(record);
    if (!parsed.success) throw new Error(`Invalid sales fields at CSV line ${info.lines}`);
    const row = parsed.data;
    return {
      modelCode,
      marketCode: row.market_code,
      volume2024: row.volume_2024,
      volume2025: row.volume_2025,
      volume2030: row.volume_2030,
      sourceFile: file,
      sourceRow: info.lines,
    };
  });
}

function validateUnique(rows: NewSale[]) {
  const keys = new Set<string>();
  for (const row of rows) {
    const key = JSON.stringify([row.modelCode, row.marketCode]);
    if (keys.has(key)) throw new Error("Duplicate model/market pair in sales input");
    keys.add(key);
  }
}

function selfCheck() {
  const file = "synthetic - G60_G68.csv";
  const header = "market,market_code,volume_2024,volume_2025,volume_2030\n";
  const rows = parseSales(file, header + '"Invented, market",ZZ,0,17,23\n');
  assert.deepEqual(rows, [
    {
      modelCode: "G60",
      marketCode: "ZZ",
      volume2024: 0,
      volume2025: 17,
      volume2030: 23,
      sourceFile: file,
      sourceRow: 2,
    },
  ]);
  assert.equal(parseSales("synthetic - F99.csv", header + "Ignored,ZZ,1,2,3")[0].modelCode, "F99");
  assert.equal(parseSales(file, header + "\nIgnored,ZZ,1,2,3")[0].sourceRow, 3);
  for (const invalid of ["", "-1", "1.5", "NaN", "2147483648"])
    assert.throws(() => parseSales(file, header + `Ignored,ZZ,${invalid},2,3`));
  assert.throws(() => parseSales(file, header + "Ignored,,1,2,3"));
  assert.throws(() => parseSales(file, "market_code\nZZ"));
  assert.throws(() => parseSales(file, header));
  assert.throws(() => parseSales("unknown.csv", header + "Ignored,ZZ,1,2,3"));
  validateUnique(rows);
  assert.throws(() => validateUnique([...rows, ...rows]));
}

async function main() {
  const { values } = parseArgs({ options: { "self-check": { type: "boolean" } } });
  if (values["self-check"]) {
    selfCheck();
    console.log("sales self-check ok");
    return;
  }
  const directory = "data/sales";
  const files = readdirSync(directory)
    .filter((file) => file.endsWith(".csv"))
    .sort();
  if (!files.length) throw new Error("No sales CSV files found");
  const rows = files.flatMap((file) =>
    parseSales(file, readFileSync(`${directory}/${file}`, "utf8")),
  );
  validateUnique(rows);

  if (existsSync(".env")) process.loadEnvFile();
  const connectionString = process.env.DATABASE_URL_UNPOOLED || process.env.DATABASE_URL;
  if (!connectionString) throw new Error("DATABASE_URL must be set");
  const url = new URL(connectionString);
  url.hostname = url.hostname.replace("-pooler.", ".");
  const pool = new pg.Pool({ connectionString: url.toString() });
  try {
    const db = drizzle({ client: pool });
    await db.transaction(async (tx) => {
      await tx.execute(sql`SET LOCAL search_path TO public, pg_catalog`);
      await tx.execute(sql.raw(readFileSync("migrations/0001_sales.sql", "utf8")));
      const stored = await tx
        .insert(sales)
        .values(rows)
        .onConflictDoUpdate({
          target: [sales.modelCode, sales.marketCode],
          set: {
            volume2024: sql`excluded.volume_2024`,
            volume2025: sql`excluded.volume_2025`,
            volume2030: sql`excluded.volume_2030`,
            sourceFile: sql`excluded.source_file`,
            sourceRow: sql`excluded.source_row`,
          },
        })
        .returning();
      const byKey = new Map(
        stored.map((row) => [JSON.stringify([row.modelCode, row.marketCode]), row]),
      );
      if (
        stored.length !== rows.length ||
        rows.some((row) => {
          const result = byKey.get(JSON.stringify([row.modelCode, row.marketCode]));
          return (
            !result ||
            Object.entries(row).some(([key, value]) => result[key as keyof typeof result] !== value)
          );
        })
      )
        throw new Error("Stored sales values do not match the CSV input");
    });
    console.log(`Imported and verified ${rows.length} sales rows from ${files.length} CSV files`);
  } finally {
    await pool.end();
  }
}

main().catch((error: unknown) => {
  // Avoid logging database errors or parser diagnostics containing private source data.
  const cause = error instanceof Error && error.cause ? error.cause : error;
  const code = cause && typeof cause === "object" && "code" in cause ? cause.code : undefined;
  console.error(
    "Sales import failed; no changes from the import transaction were committed.",
    typeof code === "string" && /^[A-Z0-9_]+$/.test(code) ? `Error code: ${code}` : "",
  );
  process.exitCode = 1;
});
