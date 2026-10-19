"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import ResearchBoard from "../components/ResearchBoard";
import V6Desk from "../components/V6Desk";

export default function AnalysisPage() {
  const router = useRouter();

  useEffect(() => {
    // Seamlessly forward to unified overview in detailed analysis mode
    router.replace("/dashboard?view=detailed");
  }, [router]);

  return (
    <ResearchBoard
      title="Analysis"
      lede="The Multi-Agent Analysis Desk is unified into the primary Overview Cockpit with instant toggle between Compact and Detailed views."
    >
      {() => (
        <V6Desk defaultTab="trades" hideTickers={true} />
      )}
    </ResearchBoard>
  );
}
