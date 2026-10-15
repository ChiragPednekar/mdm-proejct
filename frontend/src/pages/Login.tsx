import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { FlaskConical } from "lucide-react";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui/primitives";
import { Field, Input } from "../components/ui/Form";

const schema = z.object({
  username: z.string().trim().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});
type Values = z.infer<typeof schema>;

export default function Login() {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });

  const onSubmit = async (v: Values) => {
    setError(null);
    try { await login(v.username, v.password); } catch (e) { setError(e instanceof Error ? e.message : "Sign-in failed"); }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-canvas p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-lg bg-ink text-[#5eead4]"><FlaskConical className="size-5" /></span>
          <div>
            <p className="text-sm font-semibold">Smart Warranty Intelligence</p>
            <p className="text-xs text-ink-3">Service operations &amp; failure prediction</p>
          </div>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="rounded-lg border border-line bg-surface p-5">
          <h1 className="mb-4 text-base font-semibold">Sign in</h1>
          <div className="space-y-3">
            <Field label="Username" htmlFor="username" error={errors.username?.message}>
              <Input id="username" autoComplete="username" aria-invalid={!!errors.username} {...register("username")} />
            </Field>
            <Field label="Password" htmlFor="password" error={errors.password?.message}>
              <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
            </Field>
            {error && <p role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{error}</p>}
            <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Sign in</Button>
          </div>
        </form>
        <p className="mt-3 text-center text-[11px] text-ink-4">
          Demo accounts (development seed): admin · manager · tech.ravi — password from DEMO_USER_PASSWORD
        </p>
      </div>
    </div>
  );
}
