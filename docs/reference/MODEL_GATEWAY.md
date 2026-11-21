# Optional private model gateway contract

Default extraction uses a real bounded LangGraph with deterministic text candidates; it is not an LLM. To add an approved hosted/local model, implement an HTTPS service with this contract, then configure ENABLE_MODEL_EGRESS=true, MODEL_GATEWAY_URL and MODEL_GATEWAY_TOKEN. The app supplies a fixed task, source pages and a JSON response schema. No ERP or business tools are available to the model.

Request: `{task: "extract-procurement-candidates-v1", pages: ["..."], response_schema: {...}, instructions: "..."}` with a bearer integration token.

Response:

```json
{"model_version":"approved-model-and-prompt-v1","candidates":[{"field":"quantity","page":1,"quote":"Quantity: 100","suggested_value":"100"}]}
```

Use a maximum 40,000-character input and a bounded response. The app verifies typed results and exact source-quote presence; candidate acceptance is separate human review. A missing configuration returns 503 without changing facts. Real gateway behavior, model quality, billing, timeout handling and data terms remain unverified. A fixture test validates the quote check only. Do not claim end-to-end LLM quality from that test.
