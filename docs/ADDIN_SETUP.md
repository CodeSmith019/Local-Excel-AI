# Excel AI (Local) — Task Pane Add-in Setup Guide

This guide walks you through loading the Excel AI chat interface directly inside Microsoft Excel desktop on Windows as a native task pane.

---

## 🏗️ Architecture Overview

The Excel AI add-in uses the standard Microsoft Office Add-in XML manifest. The task pane runs the existing local web frontend (`https://localhost:8443/index.html`) rendered via Windows Edge WebView2.

```
┌──────────────────────────────────────────────────────────────┐
│                    Microsoft Excel Desktop                   │
│  ┌───────────────────────┐   ┌────────────────────────────┐  │
│  │ Active Sheet / Range  │   │ Task Pane (WebView2)       │  │
│  │ (e.g. employees.xlsx) │   │ https://localhost:8443     │  │
│  └──────────▲────────────┘   │ - Model status (green dot) │  │
│             │ COM            │ - Excel status (green dot) │  │
│             │ (xlwings)      │ - SSE chat + preview cards │  │
│             ▼                └─────────────▲──────────────┘  │
│  ┌───────────────────────┐                 │                 │
│  │ FastAPI Backend       │◄── HTTPS / SSE ─┘                 │
│  │ (port 8443)           │                                   │
│  └──────────▲────────────┘                                   │
└─────────────┼────────────────────────────────────────────────┘
              │ HTTP :8080
              ▼
   ┌──────────────────────┐
   │ llama-server.exe     │
   │ (Dell: Qwen 7B       │
   │  Yoga: GPT-OSS 20B)  │
   └──────────────────────┘
```

> **Key Rule**: The UI does not depend on Office JavaScript APIs for spreadsheet modifications. All workbook operations are performed safely by the FastAPI backend using `xlwings` on the dedicated COM worker thread.

---

## 📋 1. One-Time Prerequisites

Office add-ins embedded in desktop Excel require a valid local HTTPS certificate and vendored offline Office.js files.

### A. Install and Trust Development Certificates
Office desktop requires `https://` on localhost. Generate and trust the development certificates using Node.js:

```powershell
npx office-addin-dev-certs install
```

This creates the certificate files in:
- `%USERPROFILE%\.office-addin-dev-certs\localhost.crt`
- `%USERPROFILE%\.office-addin-dev-certs\localhost.key`
- `%USERPROFILE%\.office-addin-dev-certs\ca.crt`

And automatically installs the root CA into the Windows Current User **Trusted Root Certification Authorities** store.

### B. Verify Icons and Offline Office.js
The project includes self-contained icon assets and local Office.js files:
- Generated PNG icons: `frontend/assets/icon-16.png`, `icon-32.png`, `icon-80.png` (generated via `python scripts/generate_icons.py` with standard library `zlib` + `struct`).
- Offline Office.js bundle: `frontend/vendor/office/office.js`.

---

## 🚀 2. Sideloading via Shared Folder Catalog

Microsoft Excel desktop supports sideloading add-in manifests using a local network share (UNC path).

### Step 1: Share the `addin` Folder
1. Open PowerShell or Command Prompt in the project folder and note your PC name:
   ```powershell
   hostname
   # or $env:COMPUTERNAME
   ```
2. In Windows File Explorer, navigate to your project directory.
3. Right-click the `addin` folder and select **Properties**.
4. Switch to the **Sharing** tab and click **Advanced Sharing...**.
5. Check **Share this folder**.
6. Set the **Share name** to:
   ```text
   excel-ai-addin
   ```
7. Click **Permissions** and ensure your Windows account (or `Everyone`) has **Read** permission.
8. Click **OK**, then **OK**, then **Close**.
9. Test that your share is accessible by typing the UNC path into File Explorer's address bar:
   ```text
   \\<PC-NAME>\excel-ai-addin
   ```
   *(Replace `<PC-NAME>` with your actual hostname, e.g. `\\DELL-G15\excel-ai-addin`)*

---

### Step 2: Register the Catalog in Microsoft Excel
1. Open Microsoft Excel desktop.
2. Click **File** > **Options** (bottom-left).
3. In the Excel Options dialog, select **Trust Center** on the left.
4. Click the **Trust Center Settings...** button.
5. In the Trust Center dialog, select **Trusted Add-in Catalogs** on the left.
6. In the **Catalog URL** field, enter your full UNC share path:
   ```text
   \\<PC-NAME>\excel-ai-addin
   ```
7. Click **Add catalog**.
8. **Crucial**: In the catalog table, locate your URL and check the box under **Show in Menu**.
9. Click **OK** to close Trust Center Settings, then click **OK** to close Excel Options.
10. **Completely restart Microsoft Excel** so the new catalog is loaded.

---

### Step 3: Insert the Add-in
1. Launch Excel and open any test workbook (e.g. `tests\fixtures\employees.xlsx`).
2. Go to the ribbon:
   - On Microsoft 365: **Home** > **Add-ins** > **More Add-ins** (or **Insert** > **Add-ins** / **Get Add-ins**).
3. In the Office Add-ins dialog, select the **SHARED FOLDER** tab at the top.
4. You will see **Excel AI (Local)** listed.
5. Select **Excel AI (Local)** and click **Add**.

---

### Step 4: Launch the Task Pane
1. Look at the **Home** tab ribbon on the far right.
2. You will see a new group labeled **Excel AI** with the green Excel AI button.
3. Click the **Excel AI** button.
4. The task pane opens on the right side of Excel displaying the Excel AI interface!
5. Verify that:
   - **Model** status dot is **Green** (indicating `llama-server` is reachable).
   - **Excel** status dot is **Green** (indicating active connection to the open workbook).

---

## 🛠️ 3. Troubleshooting

### Problem: Blank Task Pane or Certificate Error
- **Symptom**: Task pane opens but remains blank, shows `NET::ERR_CERT_AUTHORITY_INVALID`, or displays an error that localhost cannot be loaded.
- **Fix**:
  1. Verify the certificate was installed:
     ```powershell
     npx office-addin-dev-certs install
     ```
  2. Test in Microsoft Edge: Open `https://localhost:8443/index.html` directly in Edge. If Edge shows a certificate warning, click the certificate icon to confirm trust or re-run the certificate installer.
  3. Verify that `scripts\start_backend_https.bat` is running.

### Problem: Clearing the Office Add-in Cache
- **Symptom**: Modifications to `manifest.xml` or frontend assets do not update, or the task pane gets stuck in a stale state.
- **Fix**: Clear the Office WebView2 cache directory:
  ```powershell
  # Close Excel completely first, then run:
  Remove-Item -Path "$env:LOCALAPPDATA\Microsoft\Office\16.0\Wef\*" -Recurse -Force -ErrorAction SilentlyContinue
  ```

### Problem: Shared Folder Does Not Show in "My Add-ins"
- **Symptom**: The "SHARED FOLDER" tab is missing or empty in the Add-ins dialog.
- **Fix**:
  1. Ensure the catalog path uses the UNC format `\\<PC-NAME>\excel-ai-addin`, NOT `C:\...` or `\\localhost\...` (Office requires the actual machine name for catalog shares).
  2. Verify that **Show in Menu** is checked in **Trust Center > Trusted Add-in Catalogs**.
  3. Check Task Manager to make sure all background `EXCEL.EXE` processes are terminated, then launch Excel again.

### Problem: Port Conflict
- **Symptom**: Backend fails to bind to port 8443 or port 8080.
- **Fix**: Run `scripts\stop_all.bat` to terminate any hanging instances, or check which process is holding the port:
  ```powershell
  Get-NetTCPConnection -LocalPort 8443 -ErrorAction SilentlyContinue
  ```

### Fallback Mode: Browser Beside Excel
If enterprise security policy restricts sideloading or sharing folders on your machine, you can run Excel AI in **Browser Mode**:
1. Run `scripts\start_backend.bat dell` (or `start_backend_https.bat`).
2. Open `http://127.0.0.1:8000/` (or `https://localhost:8443/`) in Microsoft Edge or Chrome.
3. Snap the browser window next to your Excel window.
All functionality (model status, COM sheet introspection, diff preview, undo) works identically!

