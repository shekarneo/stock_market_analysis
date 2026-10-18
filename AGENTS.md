# Agent Rules & Repository Invariants

## 1. UI Documentation Invariant (MANDATORY)
Whenever ANY user interface file, component, page, or option under `apps/web/` is modified, created, or removed:
- You **MUST** update [`docs/UI_WALKTHROUGH.md`](file:///home/neo/work/personal/stock_market_analysis/docs/UI_WALKTHROUGH.md) in the exact same task.
- The document must describe what the page/feature is for, what every single button, toggle, dropdown, input, badge, and metric means, and how it behaves.
- Do not leave any new or modified UI element undocumented.

## 2. Dev Server & Cache Invariant
- **DO NOT** run `npm run build` in `apps/web` while `next dev` is running concurrently in background. Doing so modifies `.next` cache and causes `Cannot find module` runtime failures.
- If builds are needed, stop the dev server, run the build, and then restart the dev server or run `npm test`.

## 3. Financial & Operational Safety Invariants
- **Fail-Closed Execution**: Real money execution remains locked behind operator authentication, explicit modal confirmation, and the hardware/software Kill Switch.
- **Simulation Isolation**: Paper trading simulated orders must never interact with live broker accounts.
- **Truth in Data**: Never replace missing or null values with zero in financial ledgers or spot tickers.
