# AI CI/CD bot analysis - run `20261107-203927-failure`

*ai-cicd-bot rule-engine v1.0 (deterministic)* - generated 2026-11-07T20:39:28.155Z

## 1. Executive summary

Run 20261107-203927-failure FAILED: 'Unit tests' failed (4 failed, 17 passed). Root cause (95% confidence): Percentage not normalised in apply_discount() (app/pricing.py:23). Production impact: None. The pipeline stopped at unit tests; no artifact was built or deployed. A minimal fix is proposed and awaits human approval.

## 2. Pipeline status

**FAILED** (FAILED) - failed stage: `unit_tests` - duration 0.40s  
Commit `b46a02bfaab3` "PRICE-142: simplify discount calculation" by dev.bob

## 3. Stage-by-stage status

| # | Stage | Status | Time | Result |
|---|---|---|---|---|
| 1 | Checkout & environment validation | **PASS** | 0.00s | tree b46a02bfaab3, 18 files, python 3.13.18 |
| 2 | Dependency installation | **PASS** | 0.00s | 1/1 resolved; app runtime uses stdlib only |
| 3 | Lint, static & secret checks | **PASS** | 0.01s | 15 files, 0 errors, 0 secrets |
| 4 | Unit tests | **FAIL** | 0.38s | 4 failed, 17 passed |
| 5 | Build & package artifact | **SKIPPED** | 0.00s | skipped: upstream stage 'unit_tests' failed |
| 6 | Integration & deployment validation | **SKIPPED** | 0.00s | skipped: upstream stage 'unit_tests' failed |
| 7 | Publish pipeline report | **PASS** | 0.00s | 2 reports published |

Passed work: Checkout & environment validation, Dependency installation, Lint, static & secret checks, Publish pipeline report  
Failed work: Unit tests  
Not run: Build & package artifact, Integration & deployment validation

## 4. Root-cause analysis

**Percentage not normalised in apply_discount() (app/pricing.py:23)**

Class `unit_test_regression / calculation_defect` - playbook `PB-001 percentage-scale-error` - confidence **95%**

The latest commit changed app/pricing.py:23 in apply_discount() to multiply by 'discount_pct' directly. 'discount_pct' is on a 0-100 scale, so a 10% discount is applied as 1000%. Every failing assertion is consistent with this: observed discounts are exactly 100x the expected value, and totals go negative.

Confidence signals:
- +0.55 percentage variable multiplied without /100 on the failing code path
- +0.20 suspect line was modified in the latest commit
- +0.15 3 assertion(s) off by exactly 100x (scale error signature)
- +0.05 all failing tests share the suspect module

## 5. Supporting evidence

1. **4 of 21 unit tests failed** - `logs/04_unit_tests.log`

   ```
   FAILED tests.unit.test_orders::test_quote_with_discount
   FAILED tests.unit.test_pricing::test_ten_percent_discount_amount
   FAILED tests.unit.test_pricing::test_ten_percent_discount_total
   FAILED tests.unit.test_pricing::test_discount_then_tax
   ```
2. **test_quote_with_discount: actual value is exactly 100x expected** - `test-reports/junit-unit.xml`

   ```
   assert '2500.00' == '25.00'
   ```
3. **test_ten_percent_discount_amount: actual value is exactly 100x expected** - `test-reports/junit-unit.xml`

   ```
   assert Decimal('2000.00') == Decimal('20.00')
   ```
4. **test_discount_then_tax: actual value is exactly 100x expected** - `test-reports/junit-unit.xml`

   ```
   assert Decimal('1000.00') == Decimal('10.00')
   ```
5. **order totals go negative in test_ten_percent_discount_total** - `test-reports/junit-unit.xml`

   ```
   assert Decimal('-900.00') == Decimal('90.00')
   ```
6. **'discount_pct' (0-100 scale) used as a raw multiplier in apply_discount()** - `workspace:app/pricing.py:23`

   ```
   return to_money(subtotal * discount_pct)
   ```
7. **line 23 of app/pricing.py was changed by the failing commit** - `commit.diff`

   ```
   -    return to_money(subtotal * (discount_pct / HUNDRED))
   +    return to_money(subtotal * discount_pct)
   ```
8. **every failing test module imports app.pricing (directly or transitively)** - `static analysis`

   ```
   tests/unit/test_orders.py -> app/orders.py, app/pricing.py
   tests/unit/test_pricing.py -> app/pricing.py
   ```

## 6. Impact & risk assessment

- Severity: **HIGH** (customer-facing pricing)
- Release blocked: True
- Customer impact if shipped: Any discounted order would be mispriced (discount 100x too large, negative totals) - direct revenue and trust impact if released.
- Production impact now: None. The pipeline stopped at unit tests; no artifact was built or deployed.
- Blast radius:
  - app/pricing.py :: apply_discount() (defect location)
  - app/orders.py (depends on app.pricing)
  - app/service.py (depends on app.pricing)
  - HTTP API POST /orders/quote

## 7. Recommended solution & fix guide

Restore percentage normalisation: change 'discount_pct' to '(discount_pct / HUNDRED)' on app/pricing.py:23. One-line change, no behaviour change for 0% discounts.

1. Open app/pricing.py at line 23 (apply_discount).
2. Replace:  return to_money(subtotal * discount_pct)
3. With:     return to_money(subtotal * (discount_pct / HUNDRED))
4. Re-run lint and the unit test stage (targeted validation).
5. Re-run the full pipeline to rebuild the artifact and run integration tests.
6. Add the 100x-ratio assertion pattern to code review guidance for money/percentage code.

Alternatives considered:
- Change tests to match new behaviour - rejected: tests encode the pricing contract; bot may not edit tests.
- Revert the whole commit - viable, but broader than the one-line defect.

## 8. Files proposed for modification

`app/pricing.py` line 23 - normalise 0-100 percentage in apply_discount()

```diff
- return to_money(subtotal * discount_pct)
+ return to_money(subtotal * (discount_pct / HUNDRED))
```

## 9. Validation plan

1. Safety gate: allow-list, file-hash precondition, change-size limit, syntax check of app/pricing.py
2. Targeted rerun: Lint, static & secret checks, Unit tests
3. Full pipeline rerun (all 7 stages) on the patched workspace
4. Success is declared only if the full rerun status is SUCCESS

## 10. Rollback plan

- Automatic: if targeted or full validation fails, restore the byte-for-byte backups and log it
- Manual: python -m ai_bot.remediate --run-id 20261107-203927-failure --rollback
- Source control: the patch is saved as a .diff; revert it like any commit

## 11. Final outcome after remediation

**RERUN PASSED** - approved by demo.approver - rerun `20261107-203927-failure-rerun1`

| Stage | Before | Targeted | Full rerun |
|---|---|---|---|
| Checkout & environment validation | PASS | - | PASS |
| Dependency installation | PASS | - | PASS |
| Lint, static & secret checks | PASS | PASS | PASS |
| Unit tests | FAIL | PASS | PASS |
| Build & package artifact | SKIPPED | - | PASS |
| Integration & deployment validation | SKIPPED | - | PASS |
| Publish pipeline report | PASS | - | PASS |

Files changed:
- `app/pricing.py`
