export function NotConfigured() {
  return (
    <div className="rounded-lg border border-line bg-card p-4 text-sm" dir="ltr">
      Supabase is not configured for this deployment. Set <code>SUPABASE_URL</code> and{" "}
      <code>SUPABASE_PUBLISHABLE_KEY</code> for this environment in Vercel, then redeploy.
    </div>
  );
}
