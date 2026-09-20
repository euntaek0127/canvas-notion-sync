# Canvas → Notion assignment sync

Syncs published assignments from active Canvas courses into an existing Notion Agenda database every 15 minutes.

## What it does

- Imports existing assignments from matched active courses on the first run.
- Creates new assignments and updates changed titles, deadlines, URLs, course relations, and types.
- Uses a stable `Canvas Key` to prevent duplicates.
- Marks an item done when Canvas reports it submitted or graded, but never unchecks an item completed manually in Notion.
- Matches Notion course titles against Canvas course names/codes. Unmatched courses are safely skipped.

## One-time setup

### 1. Make this repository private

Open **Settings → General → Danger Zone → Change repository visibility → Private**.

### 2. Create and connect a Notion integration

1. Create an internal integration at <https://www.notion.so/profile/integrations>.
2. Copy its internal integration secret.
3. Open the Notion page containing the Agenda and Courses databases.
4. Select **••• → Connections**, then add the integration. This must give it access to both the Agenda and Courses databases.

### 3. Add encrypted GitHub Actions secrets

Open **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `CANVAS_API_TOKEN` | Canvas access token from **Account → Settings → Approved Integrations** |
| `NOTION_API_TOKEN` | Internal integration secret created above |

Do not place either token in a file, commit, issue, or workflow log.

### 4. Add GitHub Actions variables

Under **Settings → Secrets and variables → Actions → Variables**, add:

| Variable | Value |
|---|---|
| `CANVAS_BASE_URL` | Your Canvas origin, such as `https://example.instructure.com` |
| `NOTION_AGENDA_DATA_SOURCE_ID` | The Notion Agenda data-source ID |
| `NOTION_COURSES_DATA_SOURCE_ID` | The Notion Courses data-source ID |

### 5. Run the first sync

Open **Actions → Canvas to Notion Sync → Run workflow**. Review the log to confirm each Canvas course matched the intended Notion course. Future runs occur automatically every 15 minutes.

## Local test

```bash
python -m unittest discover -s tests -v
```
