"use client";

import { Suspense } from "react";
import { AgentWizard } from "@/components/builder/AgentWizard";
import { Spinner } from "@/components/ui";

export default function NewAgentPage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-24">
          <Spinner />
        </div>
      }
    >
      <AgentWizard />
    </Suspense>
  );
}
