# Security

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting:

**[Report a vulnerability](https://github.com/CheeseGOD777/spendslicer/security/advisories/new)**

Include what the issue is, how to reproduce it, and what an attacker gets. A
reply should come within a few days. This is a small volunteer project — there
is no bounty, but credit is given in the advisory and the changelog unless you
prefer otherwise.

## Threat model

### What SpendSlicer does with your data

Nothing leaves your machine. There is no SpendSlicer server, no telemetry, no
analytics, no crash reporting, and no update check. Every AWS call goes from
your machine to AWS using your own credentials.

Local state, all under `~/.cache/spendslicer/`:

| File | Contents |
| --- | --- |
| `cache.db` | Cached Cost Explorer responses and resource inventory |
| `cur.duckdb` | CUR line items, if you enabled the warehouse |
| `webview/` | Dashboard client-side cache (desktop builds) |

Delete that directory and nothing of yours remains.

### Credentials

SpendSlicer reads `~/.aws/credentials` and `~/.aws/config` through boto3's normal
resolution chain. It **never writes to either**, never logs credential values,
and never copies them anywhere.

Only read-only AWS APIs are called. There is no `Create*`, `Put*`, `Update*`,
`Modify*`, `Delete*`, or `Terminate*` call anywhere in the codebase. See
[docs/IAM.md](docs/IAM.md) for the exact list.

### The local port is a financial exposure

This is the part worth understanding, because it is not the usual "someone
could read your data" story.

Cost Explorer bills **$0.01 per request** to your AWS account. Anything that
can reach a SpendSlicer port can therefore spend your money, whether or not it
can read the response.

- **Loopback bind by default.** `127.0.0.1` only.
- **Desktop builds** mint a random token per launch and bind an OS-assigned
  port. Nothing else on the machine can drive them.
- **Self-hosted** runs are unauthenticated on loopback by default. That is a
  deliberate trade for zero-config laptop use, and it is where the residual
  risk lives.

The residual risk, stated plainly: with no token set, a web page open in your
browser can issue cross-origin `GET` requests to `127.0.0.1:8080` and cause
Cost Explorer spend. The browser's same-origin policy stops that page *reading*
the reply, and the Origin allow-list blocks state-changing methods — but the
GET still executes and still bills.

**If you bind anything other than loopback, set `SPENDSLICER_AUTH_TOKEN`.** The
server logs a warning at startup when it is unset.

```bash
export SPENDSLICER_AUTH_TOKEN="$(openssl rand -base64 32)"
```

### Defenses in place

| Control | What it stops |
| --- | --- |
| Loopback-only default bind | Remote access |
| Shared-secret token, constant-time compared | Unauthorised use; token recovery by timing |
| Origin/Referer allow-list on non-GET requests | Cross-origin CSRF |
| Host header allow-list | DNS rebinding |
| Profile names validated against local config | A request selecting arbitrary credentials or triggering an unexpected `credential_process` |
| `period` and `region` validated against allow-lists | Reflected injection and unbounded cache-key growth |
| Export paths confined; export dir created `0700` | Path traversal; other local users reading exports |
| Static asset serving containment-checked | Path traversal out of the bundle |
| API docs (`/docs`, `/redoc`) disabled | Endpoint enumeration |

### Out of scope

- **A compromised machine.** If an attacker already has your user account, they
  have your AWS credentials directly and do not need SpendSlicer.
- **AWS-side permissions.** SpendSlicer can only do what the profile's IAM policy
  allows. Grant read-only.
- **The unsigned desktop builds.** They are currently unsigned, which means the
  OS cannot verify they came from us. Verify the published SHA256, or build from
  source — see [docs/DESKTOP.md](docs/DESKTOP.md).

## Supported versions

Only the latest minor release gets security fixes.

| Version | Supported |
| --- | --- |
| 1.0.x | Yes |
| < 1.0 | No (never publicly released) |

## Dependencies

Runtime dependencies are deliberately few: boto3/botocore, FastAPI, uvicorn,
and optionally duckdb/pyarrow for CUR and pywebview for the desktop shell. Each
one is a supply-chain surface, so additions are weighed rather than assumed.
