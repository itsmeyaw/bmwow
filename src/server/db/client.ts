import "server-only";
import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";

const globalForDb = globalThis as unknown as { pool?: pg.Pool };

// Reuse one pool across dev hot reloads.
// Keep connections open: on high-latency links each new connect can time out.
const pool = (globalForDb.pool ??= new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  idleTimeoutMillis: 0,
  keepAlive: true,
}));

export const db = drizzle({ client: pool });
