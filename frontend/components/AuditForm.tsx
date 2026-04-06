"use client";

import { useState, useRef, useEffect } from "react";
import TestSelector, { TEST_OPTIONS } from "@/components/TestSelector";
import ProgressDisplay from "@/components/ProgressDisplay";
import ResultsDashboard from "@/components/ResultsDashboard";

type Phase = "form" | "running" | "done";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export default function AuditForm() {
  const [url, setUrl] = useState("");
  const [task, setTask] = useState("Navigate and use the main features of this website");
  const [selectedTests, setSelectedTests] = useState<string[]>(
    TEST_OPTIONS.map((t) => t.id)
  );
  const [useQuantization, setUseQuantization] = useState(false);
  const [phase, setPhase] = useState<Phase>("form");
  const [events, setEvents] = useState<object[]>([]);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [submittedUrl, setSubmittedUrl] = useState("");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    return () => { wsRef.current?.close(); };
  }, []);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    e.stopPropagation();

    const urlValue = url.trim();
    if (!urlValue || selectedTests.length === 0) {
      setError(urlValue ? "Please select at least one test." : "Please enter a URL.");
      return;
    }

    setSubmittedUrl(urlValue);
    setError("");
    setEvents([]);
    setReport(null);
    setPhase("running");

    try {
      const res = await fetch(`${API_BASE}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: urlValue,
          tests: selectedTests,
          task: task.trim() || "Navigate and use the main features of this website",
          use_quantization: useQuantization,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `Server error ${res.status}`);
      }
      const { run_id } = await res.json() as { run_id: string };

      const ws = new WebSocket(`${WS_BASE}/ws/${run_id}`);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as Record<string, unknown>;
        setEvents((prev) => [...prev, msg]);
        if (msg.type === "done") {
          setReport(msg.report as Record<string, unknown>);
          setPhase("done");
          ws.close();
        }
        if (msg.type === "error") {
          setError(msg.message as string);
          setPhase("done");
          ws.close();
        }
      };

      ws.onerror = () => {
        setError("WebSocket connection failed. Is the backend running on port 8000?");
        setPhase("done");
      };

      ws.onclose = (ev) => {
        if (!ev.wasClean && phase === "running") {
          setError("Connection to backend dropped unexpectedly.");
          setPhase("done");
        }
      };
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("done");
    }
  }

  function handleReset() {
    wsRef.current?.close();
    setPhase("form");
    setEvents([]);
    setReport(null);
    setError("");
    setUrl("");
  }

  return (
    <div className="flex-1 max-w-4xl mx-auto w-full px-6 py-10">
      {phase === "form" && (
        <form onSubmit={handleSubmit} className="space-y-8">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Run Accessibility Audit</h2>
            <p className="text-slate-500 mt-1 text-sm">
              Enter a URL and choose which WCAG 2.1 Level AA tests to run. Powered by
              AllenAI&apos;s OLMo2 and Molmo2 models.
            </p>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="url" className="block text-sm font-medium text-slate-700">
              Website URL <span className="text-red-500" aria-hidden="true">*</span>
            </label>
            <input
              id="url"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                         placeholder:text-slate-400"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="task" className="block text-sm font-medium text-slate-700">
              Task Description
              <span className="ml-1 text-xs font-normal text-slate-500">
                — what a real user would try to accomplish
              </span>
            </label>
            <input
              id="task"
              type="text"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <TestSelector selected={selectedTests} onChange={setSelectedTests} />

          <div className="flex items-center gap-2">
            <input
              id="quantize"
              type="checkbox"
              checked={useQuantization}
              onChange={(e) => setUseQuantization(e.target.checked)}
              className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
            />
            <label htmlFor="quantize" className="text-sm text-slate-600">
              Use 4-bit quantization{" "}
              <span className="text-slate-400">(less VRAM, slower inference)</span>
            </label>
          </div>

          <button
            type="submit"
            className="bg-blue-600 hover:bg-blue-700 text-white font-medium px-6 py-2.5
                       rounded-lg text-sm transition-colors cursor-pointer
                       focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Run {selectedTests.length} Test{selectedTests.length !== 1 ? "s" : ""}
          </button>
        </form>
      )}

      {phase === "running" && (
        <ProgressDisplay events={events} onCancel={handleReset} />
      )}

      {phase === "done" && (
        <div className="space-y-6">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
              <strong>Error:</strong> {error}
            </div>
          )}
          {report && <ResultsDashboard report={report} url={submittedUrl} />}
          <button
            onClick={handleReset}
            className="text-sm text-blue-600 hover:text-blue-700 underline
                       focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
          >
            Run another audit
          </button>
        </div>
      )}
    </div>
  );
}
