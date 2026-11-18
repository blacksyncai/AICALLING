"use client";

import { BarChart3, BellRing, Settings2, Truck, Upload } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import useSWR from "swr";
import { AlertsTab } from "@/components/track-desk/AlertsTab";
import { BoardTab } from "@/components/track-desk/BoardTab";
import { ImportTab } from "@/components/track-desk/ImportTab";
import { SettingsTab } from "@/components/track-desk/SettingsTab";
import { StatsTab } from "@/components/track-desk/StatsTab";
import type { Board } from "@/components/track-desk/types";
import { Button, PageHeader, Spinner, Tabs } from "@/components/ui";
import { fetcher } from "@/lib/api";

type Tab = "board" | "alerts" | "import" | "stats" | "settings";

export default function TrackDeskPage() {
  return (
    <Suspense fallback={<div className="flex justify-center py-16"><Spinner /></div>}>
      <TrackDesk />
    </Suspense>
  );
}

function TrackDesk() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) || "board";
  const go = (t: Tab) => router.replace(t === "board" ? "/track-desk" : `/track-desk?tab=${t}`, { scroll: false });
  const { data } = useSWR<Board>("/api/track-desk/loads?status=open&limit=1", fetcher, { refreshInterval: 30000 });
  const alerts = data?.open_alerts ?? 0;

  return (
    <div>
      <PageHeader
        title="Track Desk"
        description="AI check calls for every load. Drivers get a call or text for location, loaded status and ETA, and you only hear about the exceptions."
        action={tab !== "import" ? <Button variant="primary" onClick={() => go("import")}><Upload className="h-4 w-4" /> Import loads</Button> : undefined}
      />
      <div className="mb-5 max-w-2xl">
        <Tabs<Tab>
          value={tab}
          onChange={go}
          tabs={[
            { value: "board", label: "Board", icon: <Truck className="h-3.5 w-3.5" /> },
            { value: "alerts", label: alerts ? `Alerts (${alerts})` : "Alerts", icon: <BellRing className="h-3.5 w-3.5" /> },
            { value: "import", label: "Import", icon: <Upload className="h-3.5 w-3.5" /> },
            { value: "stats", label: "Weekly stats", icon: <BarChart3 className="h-3.5 w-3.5" /> },
            { value: "settings", label: "Settings", icon: <Settings2 className="h-3.5 w-3.5" /> },
          ]}
        />
      </div>
      {tab === "board" && <BoardTab onImport={() => go("import")} />}
      {tab === "alerts" && <AlertsTab />}
      {tab === "import" && <ImportTab onDone={() => go("board")} />}
      {tab === "stats" && <StatsTab />}
      {tab === "settings" && <SettingsTab />}
    </div>
  );
}
