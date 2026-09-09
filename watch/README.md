# watch

Uptime monitoring with no account: POST a URL + email, get DOWN/RECOVERED
alerts. Free 7 days, then $5 USDC once for a year via x402. One Cloudflare
Worker + KV + a 5-minute cron. Live: https://watch.clankerceo.workers.dev

Deploy your own: create a KV namespace, put its id in wrangler.toml, set
secrets `AGENTMAIL_API_KEY` (or swap `sendMail` for any HTTP mail API) and
`CDP_KEY_JSON` (`{"key_id":..., "key_secret":...}` for the x402 facilitator;
omit and delete `/upgrade` if you only want the free monitor), `wrangler deploy`.
