-- Policies for anon never call has_role; only signed-in users need it.
revoke execute on function public.has_role(public.app_role) from public, anon;
