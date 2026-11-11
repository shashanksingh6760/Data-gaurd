# DataGuard Data Dictionary

## 1. Orders Dataset (`orders`)

The primary transactional entity monitored by DataGuard represents customer e-commerce orders.

| Column Name | Physical Type | Semantic Type | Nullable | Uniqueness | Primary Key | Foreign Key | Validation Rules & Constraints |
|---|---|---|---|---|---|---|---|
| `order_id` | String | Identifier | No | Unique | Yes | No | Required. Format: `ORD_\d{8}`. Duplicate values trigger `DUPLICATE_ORDER_ID`. |
| `customer_id` | String | Identifier | No | Non-unique | No | Yes (`customers.customer_id`) | Required. Must exist in `customers.csv`. Missing foreign key triggers `FOREIGN_KEY_VIOLATION`. |
| `order_amount` | Float64 | Metric | No | Non-unique | No | No | Required. Minimum value: $\ge 0.00$. Negative values trigger `INVALID_ORDER_AMOUNT`. |
| `order_status` | String | Categorical | No | Non-unique | No | No | Required. Allowed values: `PLACED`, `SHIPPED`, `DELIVERED`, `CANCELLED`. Unrecognized values trigger `INVALID_ORDER_STATUS`. |
| `payment_method` | String | Categorical | No | Non-unique | No | No | Required. Allowed values: `UPI`, `CARD`, `COD`, `NET_BANKING`. Unrecognized values trigger `INVALID_PAYMENT_METHOD`. |
| `customer_email` | String | Contact Info | Yes | Non-unique | No | No | Nullable (~2% baseline null rate). If present, must match RFC-5322 email regex pattern. Invalid syntax triggers `INVALID_EMAIL_FORMAT`. |
| `quantity` | Integer | Metric | No | Non-unique | No | No | Required. Minimum value: $\ge 1$. Decimal or non-positive values trigger `INVALID_QUANTITY`. |
| `order_timestamp` | Datetime (ISO-8601 UTC) | Temporal | No | Non-unique | No | No | Required. Format: `YYYY-MM-DDTHH:MM:SSZ`. Cannot be in the future (5-minute clock drift buffer). Future dates trigger `FUTURE_TIMESTAMP`. |
| `updated_at` | Datetime (ISO-8601 UTC) | Temporal | No | Non-unique | No | No | Required. Must satisfy `updated_at >= order_timestamp`. Chronological inversion triggers `TIMESTAMP_ORDER_VIOLATION`. |

### Pipeline Lineage Columns (Added during Transformation)

| Column Name | Physical Type | Description |
|---|---|---|
| `_ingested_at` | String (ISO-8601 UTC) | Exact timestamp when the record was processed and transformed by DataGuard. |
| `_run_id` | String | Foreign key reference to `pipeline_runs.run_id`. |

---

## 2. Customers Dataset (`customers`)

Reference dataset used for referential integrity and foreign key validation.

| Column Name | Physical Type | Semantic Type | Nullable | Uniqueness | Primary Key | Description |
|---|---|---|---|---|---|---|
| `customer_id` | String | Identifier | No | Unique | Yes | Format: `CUST_\d{6}`. Primary customer identity key. |
| `customer_name` | String | Demographic | No | Non-unique | No | Customer full name. |
| `created_at` | String (ISO-8601 UTC) | Temporal | No | Non-unique | No | Account registration timestamp. |

---

## 3. Quarantine Rejected Records (`rejected_<run_id>.csv`)

Stores all rows that failed schema, business, or referential constraints.

| Column Name | Type | Description |
|---|---|---|
| *(original columns)* | String | Exact un-sanitized row values as received in the source input CSV. |
| `_rejection_source_file` | String | Path to the source file where the record originated. |
| `_rejection_run_id` | String | Pipeline execution identifier. |
| `_rejection_error_code` | String | Machine-readable error code (e.g., `INVALID_ORDER_AMOUNT`, `FOREIGN_KEY_VIOLATION`). |
| `_rejection_reason` | String | Human-readable explanation of why the record was rejected. |
| `_rejection_timestamp` | String (ISO-8601 UTC) | Exact timestamp when quarantine segregation occurred. |

---

## 4. Error Codes Reference

| Error Code | Severity | Trigger Condition |
|---|---|---|
| `MISSING_REQUIRED_FIELD` | Critical | Column is missing from CSV or required field contains null/whitespace. |
| `DUPLICATE_ORDER_ID` | Critical | Duplicate primary key encountered within the batch or previously processed. |
| `INVALID_ORDER_AMOUNT` | Critical | Value cannot be parsed as a float, or value $< 0.00$. |
| `INVALID_QUANTITY` | Critical | Value is not an integer, or value $\le 0$. |
| `INVALID_ORDER_STATUS` | Critical | Status string is not in `['PLACED', 'SHIPPED', 'DELIVERED', 'CANCELLED']`. |
| `INVALID_PAYMENT_METHOD` | Critical | Payment string is not in `['UPI', 'CARD', 'COD', 'NET_BANKING']`. |
| `INVALID_EMAIL_FORMAT` | Warning | Non-null email string fails regex validation (`^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$`). |
| `INVALID_TIMESTAMP` | Critical | String cannot be parsed into an ISO-8601 UTC datetime. |
| `TIMESTAMP_ORDER_VIOLATION` | Critical | `updated_at` timestamp is earlier than `order_timestamp`. |
| `FUTURE_TIMESTAMP` | Critical | `order_timestamp` is greater than execution time ($+ 5\text{min}$ buffer). |
| `FOREIGN_KEY_VIOLATION` | Critical | `customer_id` does not exist in `customers.csv`. |
| `SCHEMA_UNEXPECTED_COLUMN` | Warning | Extra un-configured column present when strict schema mode is enabled. |
