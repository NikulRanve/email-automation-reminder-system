# Validation & Testing Protocol

This document establishes the verification procedures, testing standards, and validation checklists to confirm that each implemented feature functions as expected.

---

## 1. Testing Strategy

The system enforces a tiered testing approach:

```
┌──────────────────────────────────────┐
│       End-to-End System Tests        │  (Full cycle: Ingestion -> Validation -> Schedule -> Simulation -> SQLite -> Reports)
├──────────────────────────────────────┤
│       Integration Tests              │  (DB CRUD, Concurrency Locks, Multi-Process Restart, Scheduler-Trigger sync)
├──────────────────────────────────────┤
│       Unit Tests                     │  (Regex patterns, template escaping, date parsers, config loaders)
└──────────────────────────────────────┘
```

---

## 2. Validation Checklist per Increment

Whenever a new module or feature is implemented, the implementation report must provide:

1. **Static Analysis & Syntax Check**:
   - Verification that Python syntax compiles without syntax or type errors.
2. **Unit / Component Test**:
   - Dedicated test script or `pytest` function isolating the new component.
3. **Reproducible Validation Command**:
   - Exact terminal command to run and expected console output.
4. **Edge Case Verification**:
   - Handling of null values, malformed date strings, or connection timeouts.

---

## 3. Standard Verification Commands

* **Run all tests**:
  ```bash
  pytest -v tests/
  ```
* **Run specific module unit test**:
  ```bash
  pytest -v tests/test_<module_name>.py
  ```
* **Run normal demonstration pipeline**:
  ```bash
  python main.py
  ```
* **Run processing summary and audit report**:
  ```bash
  python main.py --report
  ```
* **Export summary and history CSV reports**:
  ```bash
  python main.py --export-csv
  ```
* **Launch interactive Streamlit dashboard**:
  ```bash
  streamlit run app.py
  ```
