# Boutique Weekly Summary

A weekly sales report for a small Bengali clothing and jewellery boutique in
Melbourne. It reads the shop's Excel sales workbook, checks the data, and
produces a short plain-English summary that answers two questions:

1. **What should I reorder?**
2. **Which products actually make money?**

I built it for my mum's real business, so it has a real user. The first
version of this project analysed a public UK retail dataset; that version is
preserved in the git tag `v1-uci-portfolio`.

## Privacy

The shop's real data is never in this repository.

- Real files live in `data/private/`, which is gitignored. A test fails if
  anything under it is ever tracked by git.
- Customer names are replaced with a keyed hash (HMAC-SHA256) inside the
  importer and never reach reports, logs or outputs. Suburb and payment method
  are dropped.
- The weekly report is built from plain arithmetic and templates. No LLM is
  involved, so no business data is sent to a third party.
- The demo, tests and screenshots use a synthetic workbook with invented names
  and perturbed prices (`src/synthetic/`).

## Try the demo

```bash
pip install -r requirements.txt
python -m src.run --profile synthetic
```

This reads `data/synthetic/boutique_synthetic.xlsx` and writes
`reports/demo/weekly_<date>.html` and `.txt`. No secrets are needed.

## Use it on the real workbook

1. Copy `.env.example` to `.env` and set `CUSTOMER_HASH_SALT` (and the `SMTP_*`
   settings if you want the report emailed).
2. Save the emailed workbook into `data/private/inbox/`.
3. Run `python -m src.run --profile private` (add `--send` to email it).

The run prints an import check, writes the report to `data/private/output/`,
and moves the workbook to `data/private/archive/`. If the data has critical
problems the report is marked "not trusted", and it is never emailed or archived.

Exit codes: `0` ok, `1` data not trusted, `2` setup or input problem, `3` email failed.

### Workbook layout

| Sheet | Required | Used for |
|---|---|---|
| `Sales` | yes | One row per sale line. Refunds have a Sale ID ending `-R` and a negative quantity. |
| `Buy Prices` | yes | What was paid per item, per product, per year. |
| `Simple Summary` | no | Its totals are checked against the Sales sheet. |
| `Stock & Orders` | no | Switches on reorder advice. |

To create the stock sheet, run
`python -m src.run --profile private --stock-template data/private/stock_template.xlsx`,
fill in the numbers, and copy the sheet into the workbook. Columns: stock on
hand, count date, weeks for a shipment to arrive, minimum order, and what is
already on order.

## How the answers are worked out

- **Profit and margin** use the buy price for the year of each sale. Refunded
  items are assumed to go back on the shelf. Sales with no buy price are left
  out of profit and flagged.
- **Sales velocity** is units per week over the last 13 weeks. Stock-outs and the
  COVID lockdown (read from the `Business Event` labels) are excluded, so a
  product that was unavailable does not look unpopular.
- **Festival effect** is learned from the `Festival / Occasion` labels in the
  shop's own history (for example sarees sell several times faster around Durga
  Puja). Upcoming dates come from `config/festivals.yaml`; check them, because
  several festivals follow the lunar calendar.
- **Reorder suggestion** estimates demand over the shipment time plus a week,
  scaled for any festival in that period, adds a safety buffer, and subtracts
  stock on hand and stock already on order. Products with few recent sales are
  marked as rough guesses.

## Project layout

```
src/
  adapters/     read the workbook into the standard schema
  validation/   import checks and the report of problems
  metrics/      profit, velocity, festival patterns, reorder suggestions
  reports/      weekly summary (text and HTML) and email delivery
  synthetic/    generator for the demo workbook
  privacy.py    customer hashing
  run.py        command-line entry point
config/festivals.yaml   upcoming festival dates
data/private/           real data (gitignored)
data/synthetic/         demo workbook
reports/demo/           demo report
tests/
```

## Tests

```bash
pytest tests/ --cov=src
```

The suite uses only synthetic data and covers the adapter, validation,
metrics, report, delivery, command line and the privacy guards.

## Roadmap

- **Phase 1 (done):** import, validation, metrics, weekly summary, email.
- **Phase 2:** a simple mobile-friendly dashboard for digging deeper.
- **Phase 3 (optional):** a plain-English question layer (RAG), off by default
  behind a feature flag, and demand forecasting.

The first version (a dbt, dashboard and LLM-narrative stack built on the UCI
retail dataset) is no longer in the tree. It is still in git history before
this rework.
