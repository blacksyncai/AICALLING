"use client";

import { Bot, Plus } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { AgentStack } from "@/components/agents/AgentStack";
import { NewAgentChooser } from "@/components/builder/NewAgentChooser";
import { Button, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import type { Agent } from "@/lib/types";

export default function AgentsPage() {
  const { data: agents, mutate, error } = useSWR<Agent[]>("/api/agents/", fetcher);
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Agents"
        description="Each agent is a voice persona with its own prompt, voice, knowledge and actions."
        action={
          <Button variant="primary" onClick={() => setOpen(true)}>
            <Plus className="h-4 w-4" /> New agent
          </Button>
        }
      />
      {error ? (
        <Card>
          <EmptyState icon={<Bot className="h-5 w-5" />} title="Couldn't load agents" description={error.message} />
        </Card>
      ) : !agents ? (
        <div className="flex justify-center py-20">
          <Spinner />
        </div>
      ) : agents.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Bot className="h-5 w-5" />}
            title="No agents yet"
            description="Tell us about your business and we'll build your first AI calling agent."
            action={
              <Button variant="primary" onClick={() => setOpen(true)}>
                <Plus className="h-4 w-4" /> New agent
              </Button>
            }
          />
        </Card>
      ) : (
        <AgentStack agents={agents} onChanged={() => void mutate()} onNew={() => setOpen(true)} />
      )}
      <NewAgentChooser open={open} onClose={() => setOpen(false)} />
    </>
  );
}
