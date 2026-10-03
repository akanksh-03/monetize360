# Market Research — Monetize360 Pricing Rules

These numbers aren't invented — each one traces back to a real regulation or published industry figure. This is what our rule percentages and constraints are built from.

## Ride-Hailing (Ola / Uber / Rapido)
- **Regulatory cap:** India's Road Transport Ministry (MVAG 2025) allows cab aggregators to charge up to 2x the base fare during peak hours — raised from the earlier 1.5x cap.
- **Regulatory floor:** Non-peak fares must stay at or above 50% of the base fare.
- **Driver payout floor:** Drivers must receive at least 80% of the fare, regardless of surge.
- **Surge triggers:** Rain, rush hour, and sudden demand spikes (e.g. large crowds opening the app in one area) typically trigger 2x–3x multipliers on real platforms before any regulatory cap is applied.

## E-commerce (Amazon / Flipkart — India context)
- **MRP is a legal ceiling, not a suggestion** — in India, the printed MRP caps the maximum sellable price. This is the key difference from ride-hailing: e-commerce pricing in India operates *below* a fixed ceiling, never above a dynamic one.
- **Competitive repricing:** Amazon has signaled willingness to price products 15–20% below quick-commerce rivals like Blinkit and Instamart on overlapping SKUs.
- **Elasticity-based pricing:** SKU-level elasticity pricing typically lifts margin by 400–800 basis points (4–8%).
- **Promotion optimization:** Adds a further 2–4 points of gross margin when tuned well.
- **Inventory-driven pricing:** Raise prices on high-demand, low-stock items; discount slow-moving stock to clear it — standard practice across major platforms.

## Why this matters for our engine
- These figures directly shaped the percentage values in our rule configs (see `docs/SCHEMA.md` and `backend/data/rules/`).
- The MRP ceiling and the MVAG surge cap are modeled as **hard constraints**, not rules — enforced no matter how many rules fire at once. This is what our `ec_test_07_cap_check` and `rh_test_07_cap_check` test cases specifically prove.
- This grounds our "configure once, works across domains" claim in real regulatory and market behavior, not arbitrary numbers — which is the whole point judges will be evaluating.

## Sources
- Road Transport Ministry, MVAG 2025 surge pricing guidelines (reported via Outlook Business)
- "AI-Driven Dynamic Pricing for Indian Retail and Modern Trade" — dsstream.com
- Uber, "How Surge Pricing Works" — uber.com