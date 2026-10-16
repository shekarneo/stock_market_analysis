"use client";

import ResearchBoard from "../components/ResearchBoard";
import V6Desk from "../components/V6Desk";

export default function AnalysisPage() {
  return (
    <ResearchBoard
      title="Analysis"
      lede="The agents write the thesis: news, macro, the tape, the forecast, and the risk book. The result is one call. That call does not send an order."
    >
      {() => <V6Desk />}
    </ResearchBoard>
  );
}
