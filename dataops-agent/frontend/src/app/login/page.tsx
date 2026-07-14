'use client';
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const login = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const r = await api.post("/api/v1/auth/login",
        new URLSearchParams({ username: email, password }),
        { headers: { "Content-Type": "application/x-www-form-urlencoded" } });
      localStorage.setItem("access_token", r.data.access_token);
      router.push("/dashboard");
    } catch {
      setError("Invalid email or password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-gray-900 border border-gray-800 rounded-2xl p-8">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-white">AXIOM</h1>
          <p className="text-gray-500 text-sm mt-1">Sign in to your workspace</p>
        </div>
        <form onSubmit={login} className="space-y-4">
          <input type="email" value={email} onChange={e => setEmail(e.target.value)}
            placeholder="Email" required
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-3 text-sm text-white placeholder-gray-500 outline-none focus:border-blue-500" />
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="Password" required
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-3 text-sm text-white placeholder-gray-500 outline-none focus:border-blue-500" />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button type="submit" disabled={loading}
            className="w-full py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-lg text-sm font-medium transition">
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
        <p className="text-center text-gray-500 text-xs mt-6">
          Demo: demo@acme.com / demo1234
        </p>
      </div>
    </div>
  );
}
