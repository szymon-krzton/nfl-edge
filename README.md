# NFL Edge
1. `pip install -r ingest/requirements.txt && python ingest/build_data.py` – pobiera dane do web/public/data
2. `cd web && npm install && npm run dev` – podgląd lokalny
3. Wrzuć repo na GitHub i podłącz do Netlify (netlify.toml jest gotowy). Workflow `refresh-data` odświeża dane codziennie i commituje JSON-y, a Netlify wdraża zmiany automatycznie.
