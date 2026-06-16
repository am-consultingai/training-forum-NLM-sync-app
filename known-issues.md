# Known issues & planned enhancements

Forward-looking items for the Drive -> NotebookLM sync app and its Windows packaging.
(The older `known_issues.md` covers the original sync-pipeline notes; this file is the
roadmap of requested improvements.)

## 1. Single root Drive folder (auto-create subfolders)
Today the app configures **three** separate Google Drive folders — source/input,
chunks output, and the extracted-text mirror. Simplify to **one** configured root
folder; the app creates and uses subfolders inside it, e.g.:

```
<root>/
  source/    - input content to process
  chunks/    - aggregated files NotebookLM syncs from
  mirror/    - per-file extracted text (reuse across machines)
```

- Backend: collapse the three folder IDs in `backend/app_config.py` /
  `backend/api/config.py` into one `root_drive_folder_id`; create/resolve the child
  folders via the Drive API in `backend/services/drive_sync.py` and
  `backend/services/drive_upload.py`.
- UI: replace the three folder inputs in `frontend/src/components/SettingsPanel.tsx`
  with a single root-folder picker.

## 2. First-run setup that prompts for the OAuth client file
The OAuth client JSON is currently loaded manually under **Settings -> Google
sign-in**. Move it into the **first-run flow**: after the model download, guide the
user to select their OAuth client JSON, then sign in, then choose the folder — a
simple wizard, so a non-technical user is led through setup on first open.

- Extend the first-run gate (`frontend/src/components/ModelSetupGate.tsx`) into a
  multi-step wizard that surfaces the existing `POST /api/config/oauth-client` loader
  and the `/api/auth/*` sign-in flow before the main UI appears.

## 3. "Powered by AM Consulting" footer
Add a persistent footer to the app UI reading **"Powered by AM Consulting"** with the
AM Consulting logo, hyperlinked to https://www.amconsultingai.com (open in a new tab).

- Implement in `frontend/src/App.tsx` (footer bar across the bottom). Add the logo
  asset under `frontend/src/assets/` and bundle it via the normal Vite build.

## 4. Nicer, branded installer
Improve the Inno Setup installer's look and add the AM Consulting logo.

- `win_app/installer.iss`: set `WizardImageFile` (large left-side bitmap),
  `WizardSmallImageFile` (top-right bitmap), a custom `SetupIconFile`, and refine the
  wizard wording. Provide the branded BMP/ICO assets under `win_app/`.
- Also give the app a real icon: `SetupIconFile` plus the EXE `icon=` in
  `win_app/DriveSyncManager.spec`.
