import "server-only";
import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";

const globalForDb = globalThis as unknown as { pool?: pg.Pool };

// Reuse one pool across dev hot reloads.
const pool = (globalForDb.pool ??= new pg.Pool({ connectionString: process.env.DATABASE_URL }));

export const db = drizzle({ client: pool });
