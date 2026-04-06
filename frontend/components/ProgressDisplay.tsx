"use client";

import { useEffect, useRef } from "react";
import { TEST_OPTIONS } from "./TestSelector";

interface Event {
  type: string;
  test?: string;
  test_name?: string;
  message?: string;
  index?: number;
  total?: number;
  data?: Record<string, unknown>;
}

interface Props {
  events: object[];
  onCancel: () => void;
}

const TEST_NAME: Record<string, string> = Object.fromEntries(
  TEST_OPTIONS.map((t) => [t.id, t.label])
);

function StatusDot({ result }: { result?: string }) {
  if (!result) return <span className="inline-block w-2 h-2 rounded-full bg-slate-300" />;
  const colors: Record<string, string> = {
    pass: "bg-green-500",
    fail: "bg-red-500",
    warning: "bg-yellow-500",
    error: "bg-orange-500",
  };
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${colors[result] ?? "bg-slate-400"}`} />
  );
}

export default function ProgressDisplay({ events, onCancel }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const typed = events as Event[];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const testResults: Record<string, string> = {};
  let currentTest = "";
  let totalTests = 0;
  let completedTests = 0;

  for (const ev of typed) {
    if (ev.type === "test_start") {
      currentTest = ev.test ?? "";
      totalTests = ev.total ?? totalTests;
    }
    if (ev.type === "test_complete") completedTests++;
    if (ev.type === "result" && ev.test) {
      testResults[ev.test] = (ev.data?.result as string) ?? "unknown";
    }
  }

  const progress = totalTests > 0 ? (completedTests / totalTests) * 100 : 0;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-xl font-bold text-slate-900">Running Tests…</h2>
          <button
            onClick={onCancel}
            className="text-sm text-slate-500 hover:text-red-600 transition-colors
                       focus:outline-none focus:ring-2 focus:ring-red-400 rounded px-2 py-1"
          >
            Cancel
          </button>
        </div>
        {totalTests > 0 && (
          <div className="mt-2">
            <div className="flex justify-between text-xs text-slate-500 mb-1">
              <span>{completedTests} / {totalTests} tests complete</span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
              <div
                className="h-2 bg-blue-600 rounded-full transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Per-test status pills */}
      {Object.keys(testResults).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(testResults).map(([id, result]) => (
            <span
              key={id}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full
                         bg-white border border-slate-200 text-slate-700"
            >
              <StatusDot result={result} />
              {TEST_NAME[id] ?? id}
            </span>
          ))}
          {currentTest && !testResults[currentTest] && (
            <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full
                             bg-blue-50 border border-blue-200 text-blue-700 animate-pulse">
              <span className="inline-block w-2 h-2 rounded-full bg-blue-500" />
              {TEST_NAME[currentTest] ?? currentTest}
            </span>
          )}
        </div>
      )}

      {/* Event log */}
      <div className="bg-slate-900 rounded-xl p-4 h-80 overflow-y-auto font-mono text-xs
                      text-slate-300 space-y-1">
        {typed.map((ev, i) => {
          if (ev.type === "progress") {
            return (
              <p key={i} className="text-slate-400">
                <span className="text-slate-600">  › </span>{ev.message}
              </p>
            );
          }
          if (ev.type === "status") {
            return (
              <p key={i} className="text-blue-400">
                <span className="text-blue-600">  ● </span>{ev.message}
              </p>
            );
          }
          if (ev.type === "test_start") {
            return (
              <p key={i} className="text-yellow-400 mt-2">
                ▶ Starting: {ev.test_name}
              </p>
            );
          }
          if (ev.type === "test_complete") {
            return (
              <p key={i} className="text-green-400">
                ✓ Complete: {TEST_NAME[ev.test ?? ""] ?? ev.test}
              </p>
            );
          }
          if (ev.type === "result") {
            const r = ev.data?.result as string;
            const color = r === "pass" ? "text-green-400" : r === "fail" ? "text-red-400" : "text-yellow-400";
            return (
              <p key={i} className={color}>
                {r === "pass" ? "✓" : "✗"} Result: {r?.toUpperCase()}
                {ev.data?.failure_reason ? ` — ${ev.data.failure_reason}` : ""}
              </p>
            );
          }
          if (ev.type === "error") {
            return (
              <p key={i} className="text-red-500">
                ✗ Error: {ev.message}
              </p>
            );
          }
          return null;
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
