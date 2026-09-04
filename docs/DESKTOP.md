# Desktop builds

CostSight ships as a native app for macOS and Windows. It is the same FastAPI
server and React dashboard as the self-hosted version, wrapped so you can
double-click it: the app binds a loopback port the OS picks, starts the server
in-process, and renders the dashboard in the platform's own webview (WebKit on
macOS, WebView2 on Windows).

## Install

Download the file for your platform from
[Releases](https://github.com/CheeseGOD777/costsight/releases).

| Platform | File | Notes |
| --- | --- | --- |
| macOS, Apple Silicon (M1–M4) | `CostSight-<version>-macos-arm64.dmg` | |
| macOS, Intel | `CostSight-<version>-macos-x86_64.dmg` | |
| Windows 10/11 x64 | `CostSight-<version>-windows-x64.zip` | Needs WebView2 (preinstalled on Win11 and current Win10) |

Verify the download against the `.sha256` file published alongside it:

```bash
shasum -a 256 -c CostSight-0.3.0-macos-arm64.dmg.sha256
```

---

## The unsigned-build warnings

**These builds are not code-signed or notarised.** Code signing requires an
Apple Developer account ($99/year) and a Windows certificate; those are not in
place yet. Both operating systems therefore treat the app as untrusted on first
launch.

This is worth being blunt about: the warnings are real, they look alarming, and
"just click through the scary dialog" is genuinely poor security advice. If you
are not comfortable doing that, **build it yourself** — the instructions are
below and take about five minutes. A locally built app carries no quarantine
flag and triggers no warning.

### macOS

Gatekeeper reports unsigned downloaded apps as *"CostSight is damaged and can't
be opened. You should move it to the Trash."* The app is not damaged; macOS
gives that exact message for any app carrying a quarantine attribute without a
valid signature.

After dragging CostSight to Applications, clear the flag once:

```bash
xattr -dr com.apple.quarantine /Applications/CostSight.app
```

Then open it normally. You only need to do this once per install.

### Windows

SmartScreen shows *"Windows protected your PC"*. Click **More info** →
**Run anyway**. Some corporate endpoint-protection suites block unsigned
binaries outright, in which case building from source is the way through.

---

## Where CostSight puts things

Everything lives under one directory, and nothing is written to the registry or
to system locations:

| Path | Contents |
| --- | --- |
| `~/.cache/costsight/cache.db` | SQLite cache of Cost Explorer responses |
| `~/.cache/costsight/cur.duckdb` | CUR warehouse, if configured |
| `~/.cache/costsight/webview/` | Webview localStorage (the dashboard's client-side cache) |

To uninstall: delete the app and remove `~/.cache/costsight`. That's it.

Credentials are read from `~/.aws/credentials` and `~/.aws/config`. CostSight
never writes to either.

---

## How the desktop build differs from self-hosting

| | Desktop app | `costsight-web` |
| --- | --- | --- |
| Port | OS-assigned, ephemeral | 8080 |
| Auth | Random token minted per launch | None by default |
| Window | Native webview | Your browser |
| PDF export | Unavailable (needs Node) | Works if Node is installed |

The per-launch token matters more than it might look. The server's CSRF check
only guards state-changing methods, so on a plain unauthenticated loopback bind
any web page you happen to have open could fire cross-origin `GET`s at the port.
CORS stops that page reading the response, but it does **not** stop the request
— and each one spends real Cost Explorer money. The desktop build closes that
by requiring a token nothing else knows.

---

## Building it yourself

Building locally produces an app with no quarantine flag and no warnings.

### Prerequisites

- Python 3.10+
- Node.js 20+
- macOS: Xcode command line tools (`xcode-select --install`)

### macOS

```bash
git clone https://github.com/CheeseGOD777/costsight.git
cd costsight

python3 -m venv venv && source venv/bin/activate
pip install -e ".[web,cur,exporters,desktop,build]" Pillow

./packaging/build_macos.sh
```

Output: `dist/CostSight-<version>-macos-<arch>.dmg`, plus
`dist/CostSight.app` which you can run directly.

### Windows

```powershell
git clone https://github.com/CheeseGOD777/costsight.git
cd costsight

python -m venv venv
venv\Scripts\activate
pip install -e ".[web,cur,exporters,desktop,build]" Pillow

powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

Output: `dist\CostSight-<version>-windows-x64.zip`, plus
`dist\CostSight\CostSight.exe`.

### What the build does

1. `npm ci && npm run build` in `frontend/`, which writes the bundle into
   `costsight/web/static`
2. `packaging/make_icons.py` draws the icon and emits `.png`/`.icns`/`.ico`
3. `pyinstaller packaging/costsight.spec` freezes everything into one directory
4. `hdiutil` (macOS) or `Compress-Archive` (Windows) packages it

Expect roughly 250 MB unpacked. Two thirds of that is PyArrow (~118 MB) and
DuckDB (~48 MB), which back the optional CUR warehouse. If you don't need CUR,
drop `pyarrow` and `duckdb` from the `collect_all` loop in
`packaging/costsight.spec` and the build lands around 90 MB.

---

## Signing (for maintainers)

The build scripts already contain the signing steps; they stay inert until the
credentials exist. Set these as repository secrets and the release workflow
picks them up automatically.

### macOS

| Secret | Value |
| --- | --- |
| `MACOS_CODESIGN_IDENTITY` | e.g. `Developer ID Application: Your Org (TEAMID)` |
| `APPLE_ID` | Apple ID email |
| `APPLE_APP_PASSWORD` | App-specific password, not the account password |
| `APPLE_TEAM_ID` | 10-character team ID |

The certificate also needs importing into the runner keychain before
`codesign` runs — add an `apple-actions/import-codesign-certs` step to the
macOS job with the `.p12` and its password.

`packaging/entitlements.plist` already carries the hardened-runtime exemptions
PyInstaller needs (`allow-unsigned-executable-memory`,
`disable-library-validation`) plus network client/server access.

### Windows

| Secret | Value |
| --- | --- |
| `WINDOWS_CERT_FILE` | Path to the `.pfx` on the runner |
| `WINDOWS_CERT_PASSWORD` | Its password |

Note that a fresh certificate has no SmartScreen reputation, so warnings can
persist for a while regardless. An EV certificate avoids that; a standard OV
certificate builds reputation over time.

---

## Troubleshooting

**Window opens blank.** The server is still starting. It should take about a
second; if it hangs, run the binary from a terminal with
`COSTSIGHT_LOG_LEVEL=debug` to see why.

**"The local server did not start within 45s."** Usually a port or firewall
restriction. Force a specific port with `COSTSIGHT_PORT=8080`.

**No AWS profiles listed.** CostSight reads `~/.aws/credentials` and
`~/.aws/config`. Confirm with `aws configure list-profiles`. For SSO profiles,
run `aws sso login --profile <name>` first.

**macOS: "damaged and can't be opened" persists.** Confirm the flag is gone:

```bash
xattr -l /Applications/CostSight.app
```

If `com.apple.quarantine` is still listed, re-run the `xattr -dr` command with
`sudo`.

**Windows: app closes immediately.** Usually a missing WebView2 runtime on an
older Windows 10 build. Install the
[Evergreen runtime](https://developer.microsoft.com/microsoft-edge/webview2/),
or run `CostSight.exe` from a terminal — it falls back to your default browser
when no webview is available.
