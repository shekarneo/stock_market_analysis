# UI Documentation Synchronization Rule

## Core Directive
Whenever any user interface file, page, component, modal, navigation bar, or interactive option inside `apps/web/` is added, modified, relocated, or removed, you **MUST** immediately update the corresponding section in [`docs/UI_WALKTHROUGH.md`](file:///home/neo/work/personal/stock_market_analysis/docs/UI_WALKTHROUGH.md).

## Requirements
1. **Zero Discrepancies**: Every single user-facing button, toggle, dropdown, input field, status badge, metric display, and table column must be documented with:
   - What the element does
   - Its default state and selectable options
   - Its underlying API endpoint or state impact
   - Its safety or financial compliance implications
2. **Synchronized Screenshots / Visual References**: If layout structure changes significantly, ensure descriptions match the current visual hierarchy.
3. **Checklist for Any Frontend Changes**:
   - [ ] Did you add or change a route in `apps/web/app/`? Update Section 1 & the corresponding Page Section in `docs/UI_WALKTHROUGH.md`.
   - [ ] Did you add or change buttons, switches, or form fields? Update the "Options & Controls" breakdown for that page.
   - [ ] Did you alter the Shell, Rail, or Global Header? Update Section 1 (Global Shell & Navigation).
   - [ ] Did you modify status indicators, badges, or color meanings? Update the "Status Badges & Indicators" guide.
