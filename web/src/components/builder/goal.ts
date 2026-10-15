// Goal-step helpers shared by the wizard, the Goal step, the AI assistant and the review.
import { CUSTOM_USE_CASE, type BuilderCatalog, type DraftGoal, type UseCase } from "@/lib/builder";

export type GoalUpdater = (fn: (g: DraftGoal) => DraftGoal) => void;

export const MIN_DESCRIPTION = 15;

export function useCasesFor(catalog: BuilderCatalog | undefined, industry: string | undefined): UseCase[] {
  if (!catalog) return [];
  return catalog.use_cases[industry ?? ""] ?? catalog.use_cases.other ?? [];
}

/** Selected use-case keys in order (older drafts only had `use_case`). */
export function selectedKeys(goal: DraftGoal): string[] {
  return goal.use_cases ?? (goal.use_case ? [goal.use_case] : []);
}

/** The "Create your own" description (older drafts kept it in answers.custom_goal). */
export function customDescription(goal: DraftGoal): string {
  if (goal.custom?.description !== undefined) return goal.custom.description;
  const legacy = goal.answers?.custom_goal;
  return typeof legacy === "string" ? legacy : "";
}

export function presetKeys(goal: DraftGoal): string[] {
  return selectedKeys(goal).filter((k) => k !== CUSTOM_USE_CASE);
}

/** Enough to generate: at least one preset, or a description of 15+ characters. */
export function goalReady(goal: DraftGoal): boolean {
  return presetKeys(goal).length > 0 || customDescription(goal).trim().length >= MIN_DESCRIPTION;
}

/** Fingerprint of what the assistant reviews; a change means its questions may be out of date. */
export function goalBasis(goal: DraftGoal): string {
  const keys = selectedKeys(goal);
  const custom = keys.includes(CUSTOM_USE_CASE) || presetKeys(goal).length === 0;
  const c = goal.custom ?? {};
  return JSON.stringify([
    // v4 wizard: specialty, mission and the details around it.
    goal.specialty?.key ?? "",
    goal.mission?.trim() ?? "",
    goal.additional?.trim() ?? "",
    goal.advanced ?? {},
    goal.direction ?? "",
    keys,
    custom ? [customDescription(goal).trim(), c.audience?.trim() ?? "", c.tone?.trim() ?? "", c.outcome?.trim() ?? ""] : [],
    goal.extra_instructions?.trim() ?? "",
  ]);
}

export function withKeys(g: DraftGoal, keys: string[]): DraftGoal {
  const primary = keys.find((k) => k !== CUSTOM_USE_CASE) ?? (keys.includes(CUSTOM_USE_CASE) ? CUSTOM_USE_CASE : undefined);
  return { ...g, use_cases: keys, use_case: primary };
}

