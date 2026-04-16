import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About — PointCheck",
  description:
    "PointCheck is a WCAG 2.1 & 2.2 Level AA accessibility tester built by Brendan Works, powered by Allen AI's MolmoWeb-8B vision-language model.",
};

export default function AboutPage() {
  return (
    <div className="flex-1 max-w-2xl mx-auto w-full px-6 py-14">
      <h2
        className="text-2xl font-bold tracking-tight mb-6"
        style={{ color: "var(--text)" }}
      >
        About PointCheck
      </h2>

      <div className="space-y-5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        <p style={{ color: "var(--text)" }}>
          PointCheck is a WCAG 2.1 &amp; 2.2 Level AA accessibility tester built by{" "}
          <a
            href="mailto:brendanworks@gmail.com"
            style={{ color: "var(--lime)" }}
          >
            Brendan Works
          </a>
          .
        </p>

        <p>
          Most automated accessibility tools — Axe, Lighthouse, browser
          extensions — work by inspecting the DOM. They can tell you if an
          image is missing alt text or if a button lacks an accessible name.
          What they can&apos;t do is look at the page the way a human eye would.
          That means they miss failures that only show up visually: a focus ring
          defined in CSS that gets overridden by a widget, a contrast failure
          caused by a layered background, or an element only reachable by mouse.
        </p>

        <p>
          PointCheck uses{" "}
          <a
            href="https://huggingface.co/allenai/MolmoWeb-8B"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--lime)" }}
          >
            MolmoWeb-8B
          </a>
          {" "}— Allen AI&apos;s open-source vision-language model trained for web
          navigation — to <em>see</em> the browser the way a human would.
          MolmoWeb takes a screenshot and returns a pixel coordinate, pinpointing
          exactly where the focused element is on screen. A second model,
          Molmo-7B-D, then answers a direct question about what&apos;s visible in
          that region: <em>&ldquo;Is there a visible focus indicator? Describe it.&rdquo;</em>
        </p>

        <p>
          This two-model visual pipeline catches a category of failures that
          DOM-only tools cannot: focus rings that exist in CSS but are visually
          absent, interactive content that is only reachable by mouse, and
          contrast failures on elements with composed transparent backgrounds.
        </p>

        <p>
          The rest of the test suite covers keyboard navigation, 200% zoom
          reflow, color-blindness simulation, form error handling, and a broad
          page structure check. After all checks complete, Allen AI&apos;s{" "}
          <a
            href="https://allenai.org/olmo"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--lime)" }}
          >
            OLMo-3
          </a>{" "}
          writes a plain-English executive summary — no accessibility jargon —
          covering what was found, what failed, and what to fix first.
        </p>

        <p>
          Paste any public URL, select your tests, and get a detailed
          accessibility report with visual evidence streamed live.
        </p>

        <p>
          Read the full technical writeup on{" "}
          <a
            href="https://open.substack.com/pub/brendanworks/p/your-site-passed-the-audit-its-still?r=bvfqv&utm_campaign=post&utm_medium=web"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--lime)" }}
          >
            Substack →
          </a>
        </p>

        <div
          className="mt-8 pt-6 flex flex-wrap gap-4 text-xs"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <a
            href="https://github.com/BrendanWorks/PointCheck"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--lime)" }}
          >
            View source on GitHub →
          </a>
          <a href="mailto:brendanworks@gmail.com" style={{ color: "var(--muted)" }}>
            brendanworks@gmail.com
          </a>
        </div>
      </div>
    </div>
  );
}
