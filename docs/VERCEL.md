# Deploy Stocklist on Vercel

The root `app.py` exposes Streamlit 1.59's ASGI application. Vercel detects this
Python entry point automatically. `vercel.json` enables Fluid compute, which is
required for Vercel's Python WebSocket support. Python is pinned to 3.12.

## Persistent database and first owner

Create a **dedicated SQLite Cloud database** and copy its connection URL from the
provider dashboard. The app connects directly to this shared database; it does
not replicate business records to temporary files in Vercel.

In Vercel's project settings, add these environment variables for the deployment:

| Variable | Value |
| --- | --- |
| `SQLITE_CLOUD_URL` | Full `sqlitecloud://.../database?apikey=...` URL from your database dashboard |
| `STOCKLIST_OWNER_USERNAME` | Your initial owner username |
| `STOCKLIST_OWNER_PASSWORD` | A unique password of at least 12 characters |
| `STREAMLIT_SERVER_COOKIE_SECRET` | A long random secret shared by all instances of this deployment |

Keep these values in environment settings, never Git. The first startup creates
the schema and owner account. Visitors must then sign in; provisioning does not
sign them in. Once the owner exists, remove the two initial-owner variables and
redeploy. Changing them does not reset an existing account's password.

Use separate databases for Preview and Production. Do not attach public preview
builds to the live business database. Local sample records are not uploaded.
To move existing records, download the app's SQLite backup and import it into an
empty SQLite Cloud database using the provider's import facility before launch.
The imported database must have the current Stocklist schema version.

## Vercel project settings

1. Import this repository and select the branch containing these deployment files.
2. Use the repository root as Root Directory.
3. Use the Python runtime with automatic build detection. Remove custom commands
   such as `streamlit run ...` from Build Command and any static Output Directory
   override. `requirements.txt` supplies the dependencies.
4. Add the variables above, enable Fluid compute, and redeploy.
5. Sign in, add a test product, refresh, and verify it from another browser.
   Redeploy once and confirm it remains before entering live inventory.

## Operating boundaries

- Vercel WebSockets are beta and terminate at the configured function duration
  (300 seconds here). Streamlit reconnects, but a new function instance may lose
  the browser's in-memory session. Users may need to sign in again; unsaved forms
  can be lost. Database records and committed transactions remain shared.
- Local fallback storage is disabled on Vercel. Missing database configuration
  shows a setup message rather than accepting records into disposable storage.
- Use the database provider's scheduled backups. The app's automatic *local*
  backups are disabled for cloud connections. Manual backup downloads work.
- Remote schema upgrades are deliberately not automatic. Back up the cloud
  database and plan a migration before deploying a new schema version.
- The current app serves one business per database. User roles share that
  business's records; this is not a multi-tenant public SaaS deployment.
- Test attachment/media downloads and reconnect behavior on the actual Vercel
  deployment. Streamlit keeps some generated media in each function's memory.

Local contract tests use a SQLite-backed stand-in for the provider transport.
They do not certify the provider network, Vercel build, or a live deployment.

References: [Vercel Python](https://vercel.com/docs/functions/runtimes/python),
[Vercel WebSockets](https://vercel.com/docs/functions/websockets),
[SQLite Cloud Python SDK](https://github.com/sqlitecloud/sqlitecloud-py).


## Public demo workspace

The sign-in screen offers Owner demo, Warehouse demo, Accountant demo and Read-only demo. Each button creates a private temporary sample database for that browser session, with products, stock, purchases, sales and example operations. The demo uses normal role permissions. Email sending is blocked by the business service, including when production SMTP credentials are configured.

No extra environment variables or demo cloud database are required. The live business continues to use SQLITE_CLOUD_URL; the demo never connects to it. Demo files use the operating system temporary directory, which is writable on Vercel. They are disposable and are cleaned up when leaving the demo or when its session object is released. A refresh, connection expiry or function restart may end a demo session. Do not enter real business records in the demo.

Choose Leave demo or Sign out to discard the sample workspace and return to normal business sign-in. Deploy this code revision to make the buttons available on Vercel.
