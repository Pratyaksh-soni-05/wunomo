import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen bg-gray-950 flex flex-col items-center justify-center px-6">
      <div className="text-center max-w-2xl">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-sm mb-8">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          AI Workforce Systems
        </div>
        <h1 className="text-5xl font-bold text-white mb-4">AXIOM</h1>
        <p className="text-xl text-gray-400 mb-2">AI DataOps Engineer</p>
        <p className="text-gray-500 mb-10">
          Autonomous pipeline management, data quality, incident triage, and governance — powered by Gemini.
        </p>
        <div className="flex gap-4 justify-center flex-wrap">
          <Link href="/dashboard"
            className="px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition">
            Open Dashboard
          </Link>
          <Link href="/chat"
            className="px-6 py-3 border border-gray-700 hover:border-gray-500 text-gray-300 rounded-lg font-medium transition">
            Chat with AXIOM
          </Link>
        </div>
      </div>
    </main>
  );
}
