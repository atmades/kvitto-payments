# AI_LOG

## Tools

- **Claude (Anthropic)** in chat: planning, step-by-step implementation, explanations, review.
- **ruff** and **pytest** to verify everything the model produced.
- `CLAUDE.md` in the repo keeps the project rules for the assistant.

I built the project in five small steps (skeleton → money math → payments → webhook → extras),
ran the tests after each step and asked the model to explain every part until I could
explain it myself.

## Key prompts

1. **Money math.** "Split an amount in kopecks into N payments without float. Extra kopecks go
   to the first payments, the schedule must sum exactly to the amount. Write tests that check
   these properties for all tariffs and terms, not a single example."
2. **Idempotency.** "Make POST /payments idempotent by the Idempotency-Key header: same key →
   same payment with 200. Explain what happens if two identical requests arrive at the same
   moment, and cover that case with a test."
3. **Webhook.** "Add the bank webhook: HMAC-SHA256 signature of the raw body, a status
   transition table, 409 in the exact format from the task. Make sure a parallel webhook
   cannot overwrite the status."

## Where the model was wrong and how I noticed

- **Repeated webhook.** While reviewing other solutions the model first claimed a repeated
  `succeeded → succeeded` webhook should return 200. The task says all transitions except the
  three listed are forbidden, so it is 409. I checked against the task text and kept 409.
- **Dependency style.** The first version used `db: Session = Depends(get_db)`; ruff reported
  B008. Switched to `Annotated[Session, Depends(get_db)]`.
- **Time zones.** SQLite drops the time zone, so POST returned `created_at` with `Z` and GET
  without it. Found it with a test comparing POST and GET responses; fixed in `PaymentOut`.
- **Lost test.** One test case used a non-ASCII signature written in Cyrillic; after removing
  Russian comments from the code that line would have been deleted too. I noticed it because
  the test count dropped from 82 to 81 and replaced it with `naïve-signature`.
- **Unneeded `noqa`.** The model marked imports in `conftest.py` with `# noqa: E402`; ruff
  reported RUF100 (the rule is not enabled), so the markers were removed.
- **401 vs 422.** A manual check showed that a broken body without a signature returns 422,
  not 401: FastAPI validates the body together with dependencies. The status never changes in
  either case, so I documented it instead of adding extra code.