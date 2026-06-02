# E2E CUJ Test Plan

This folder contains Playwright Critical User Journey tests.

Each file owns one user-facing workflow category. Preview-safe journeys run
without real provider credentials, while provider-backed checks are skipped
unless their matching environment variables are present.

Run these tests against the local Vite dev server on `http://127.0.0.1:5174`:

```bash
pnpm dev --host 127.0.0.1 --port 5174
pnpm test:cuj
```

Some categories still contain skipped placeholders where the app needs a more
specific mock IPC fixture or a live integration target before the journey can be
asserted end to end.

Suggested order:

1. `api-configuration.spec.ts`
2. `character-management.spec.ts`
3. `template-launch-chat.spec.ts`
4. `chat-stage.spec.ts`
5. `plugin-management.spec.ts`
6. `background-management.spec.ts`
7. `tools-workflows.spec.ts`
8. `music-cover.spec.ts`
9. `system-settings.spec.ts`
10. `error-recovery.spec.ts`
11. `live-bridge.spec.ts`
12. `responsive-visual.spec.ts`
