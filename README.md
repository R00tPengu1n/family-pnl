# Family P&L

Family finance tracking service: REST API, Telegram bot and background worker.
See `SPEC.md`.

## CSV import of operations

`POST /operations/import` with the file as the request body (`Content-Type: text/csv`).

- UTF-8 (a BOM is fine), comma or semicolon separated, at most 1 MiB and 5000 rows.
- A header row; columns in any order, names case-insensitive:

| Column     | Required | Value                                              |
|------------|----------|----------------------------------------------------|
| `date`     | yes      | `YYYY-MM-DD`                                       |
| `type`     | yes      | `income` or `expense` (transfers are not imported) |
| `amount`   | yes      | positive, a point before at most two decimals      |
| `account`  | yes      | account name as in the app                         |
| `category` | yes      | category name of the same kind as the type         |
| `currency` | no       | `RUB`, `BYN` or `USD`; empty means the account's   |
| `comment`  | no       | up to 500 characters                               |

```csv
date,type,amount,account,category,currency,comment
2026-10-20,expense,12.50,Card,Продукты,,Молоко
2026-10-20,income,2500,Card,Зарплата,BYN,
```

Names are matched ignoring case and surrounding spaces; an unknown or archived account or
category is an error, never created. Every bad cell is reported with its row (the header is
row 1), column and reason.

Query parameters: `strict=true` (default) imports nothing if any row is wrong, `strict=false`
imports the valid rows; `dry_run=true` checks everything and imports nothing.
