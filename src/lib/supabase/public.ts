import { createClient } from "@supabase/supabase-js";
import { supabaseKey, supabaseUrl } from "./env";

// Cookie-free client for public, aggregated data so pages can be cached.
export function createPublicClient() {
  return createClient(
    supabaseUrl!,
    supabaseKey!,
    { auth: { persistSession: false } },
  );
}
