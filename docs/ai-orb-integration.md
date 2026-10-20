# AI activity orbs

The frontend is Next.js 15 / React 19 with TypeScript 5.9 and Tailwind CSS 4. Component alias `@/components/ui` maps to `web/src/components/ui`; global styles are `web/src/app/globals.css`. No root-level duplicate `/components/ui` folder is needed: the existing `src` layout and `@/*` alias are the project convention. `web/components.json` records that layout for the shadcn CLI. Do not rerun `shadcn init` over the existing theme. When adding other shadcn primitives, review their semantic token requirements against our brand theme before using them.

Installed exact dependencies: `thinking-orbs@0.3.2` (React >=18), `tailwind-merge@3.7.0`. Existing `clsx@2.1.1`, `motion@12.43.0` and `lucide-react@0.468.0` are reused. The installed orb library supports every mapped OrbState, the 20/32/64 sizes, `paused`, `speed`, `dotSize` and canvas color. No context provider, remote images, fonts or extra assets are required.

`AiOrb` in `web/src/components/ui/ai-orb.tsx` implements the supplied component, with shared state helpers extracted to `ai-orb-state.ts`. Scoped and root theme changes are observed. Missing shadcn semantic colors fall back to existing BlackSync brand/neutral/error/warning tokens, without changing global page colors. Class merging is local to this component; the app's global `cn` helper is unchanged. Canvas hydration is client-only. Reduced motion uses a static frame; resting states settle after five seconds. The underlying library stops animating hidden/offscreen canvases.

## Placements

* Browser call test: replaces the phone avatar. Existing LiveKit 2.15.8 `lk.agent.state` attributes drive listening/thinking/speaking (speaking uses the streaming/composing animation). Agent audio level can also trigger composing while the phase is live. Initial attributes are read after connect and on participant arrival, so an initial listening state is not missed. Only agent participants can change it. The accessible label says speaking, not writing. Error/ended/connecting states override stale speaking. Reported speaking/audio levels are not proof that sound was heard; playback permission and caller-side audibility are not measured by this UI.
* Chat test: replaces bouncing typing dots with a small thinking orb during the existing pending HTTP request. It does not simulate streamed text or tool events.
* Radar composer: compact orb plus status while drafting or dictating, retaining the existing welcome robot. Typed-but-unsent text does not claim the microphone is listening. No workflow is activated by an animation.

`demos/ai-orb-demo.tsx` contains the supplied scripted turn and state gallery, adapted to existing brand classes. It is a design demo, not a new public route or a source of production status.

## Validation and rollback

Run from `web`:

```
node --experimental-strip-types --test src/components/ui/ai-orb-state.test.mjs
npm run typecheck
npm run build
```

The isolated browser fixture uses real UI components and a test-only LiveKit event double. It checks connection/listening/thinking/speaking/ended/error transitions, mute controls, pending chat and completion, Radar drafting, scoped colors/theme changes, resting state settling, reduced motion and page width at 390px and 1440px. It does not validate a live WebRTC audio call. Fixture and screenshots are outside the deployable tree (`/workspace/orb-review`), and the test alias is not in production configuration.

No backend, provider configuration, voice selection, prompt, recording preference or business objective changes. No API fees are introduced by the component. Roll back by reverting this integration commit, including package manifest and lockfile; no database migration is involved.
