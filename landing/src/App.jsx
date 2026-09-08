import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Mark as BrandMark } from "@app/lib/icons.jsx";
import { Board } from "./demo/Board";
import { Attribution } from "./demo/Attribution";

/* Surfaces pulls in Recharts, which is the single heaviest thing on the page
   and is not needed to read the hero. Load it when the section is close to
   the viewport, so the first paint stays cheap. */
const Surfaces = lazy(() =>
  import("./demo/Surfaces").then((m) => ({ default: m.Surfaces }))
);

function WhenNear({ children, minHeight }) {
  const ref = useRef(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    if (!("IntersectionObserver" in window)) { setNear(true); return; }
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setNear(true); io.disconnect(); } },
      { rootMargin: "600px 0px" }
    );
    if (ref.current) io.observe(ref.current);
    return () => io.disconnect();
  }, []);

  return (
    <div ref={ref} style={{ minHeight }}>
      {near ? <Suspense fallback={null}>{children}</Suspense> : null}
    </div>
  );
}

const REPO = "https://github.com/CheeseGOD777/spendslicer";
const DOC = (f) => `${REPO}/blob/main/${f}`;

/* Scroll reveal. IntersectionObserver, never a scroll listener: the page
   embeds live charts and tables, and a per-frame handler would fight them. */
function useReveal() {
  const root = useRef(null);
  useEffect(() => {
    const els = root.current?.querySelectorAll(".rise");
    if (!els?.length) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches
        || !("IntersectionObserver" in window)) {
      els.forEach((el) => el.classList.add("seen"));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        e.target.classList.add("seen");
        io.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0.12 });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  return root;
}

function Wordmark() {
  return (
    <a className="brand" href="#top" aria-label="SpendSlicer, home">
      <span className="brand-mark" aria-hidden="true"><BrandMark size={18} /></span>
      <span className="brand-word"><b>SpendSlicer</b></span>
    </a>
  );
}

function Nav() {
  return (
    <header className="nav">
      <div className="nav-in">
        <Wordmark />
        <nav className="nav-links" aria-label="Sections">
          <a href="#surfaces">Screens</a>
          <a href="#attribution">Attribution</a>
          <a href="#local">Local only</a>
          {/* <a href="#limits">Limits</a> */}
        </nav>
        <div className="nav-cta">
          <a className="lp-btn lp-btn-quiet lp-btn-sm" href={REPO}>GitHub</a>
          <a className="lp-btn lp-btn-solid lp-btn-sm" href="#install">Install</a>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="hero lp-sect">
      <div className="wrap hero-grid">
        <div className="lift">
          <h1>The console will not name the machine.</h1>
          <p className="lede">
            SpendSlicer names it, and carries the provenance of every figure. It runs on your
            own laptop against your own AWS profile &mdash; no account linking, no agent, and no
            cost data ever leaves the machine.
          </p>
          <div className="hero-cta">
            <a className="lp-btn lp-btn-solid" href="#install">Install</a>
            <a className="lp-btn lp-btn-quiet" href={REPO}>GitHub</a>
          </div>
        </div>

        <div className="hero-demo">
          <Board rows={3} />
          <p className="demo-tag">
            Live, running in this page. Sample data, not a real account.
          </p>
        </div>
      </div>
    </section>
  );
}

function AttributionSection() {
  return (
    <section id="attribution" className="lp-sect sect-rule">
      <div className="wrap">
        <div className="head-block rise">
          <h2>AWS prices the usage type. It does not name the machine.</h2>
          <p className="lede">
            This is the whole difference, and it is easier to see than to explain. Pick any
            service below. The left column is every way AWS priced it. The right names the
            machines behind the same spend. Only one of them tells you what to go and switch off.
          </p>
        </div>
        <div className="rise">
          <Attribution />
        </div>
      </div>
    </section>
  );
}

function SurfacesSection() {
  return (
    <section id="surfaces" className="lp-sect sect-rule">
      <div className="wrap">
        <div className="head-block rise">
          <h2>Every service on the bill, not a chosen few.</h2>
          <p className="lede">
            Running below, not a screenshot. Whatever Cost Explorer bills you appears here &mdash;
            EC2 and RDS alongside Lambda, ECS, OpenSearch, SQS, SNS, NAT gateways and the long tail
            of small services that quietly add up. Open a service row, filter by service, copy a
            resource ID. Audit and Export are the other two screens: a waste list of resources
            billing without earning it, and CSV, JSON or PDF written by your own machine.
          </p>
        </div>
        <div className="rise">
          <WhenNear minHeight={780}><Surfaces /></WhenNear>
        </div>
      </div>
    </section>
  );
}

function MeterSection() {
  return (
    <section id="meter" className="lp-sect sect-rule">
      <div className="wrap">
        <div className="head-block rise">
          <h2>Cost Explorer bills per request, so the meter stays on.</h2>
        </div>
        <div className="meter-grid">
          <div className="rise">
            <p className="figure meter-fig">$0.01</p>
            <p className="meter-fig-label">
              per Cost Explorer request, charged to your account, not to a vendor
            </p>
          </div>
          <dl className="facts">
            <div className="rise">
              <dt>The spend is in the window, not in a footnote</dt>
              <dd>
                Every response carries the calls spent and the estimated cost, and the session
                meter shows the running total. A design that encourages careless refetching is
                treated as a bug.
              </dd>
            </div>
            <div className="rise">
              <dt>Cached hard, and deduplicated</dt>
              <dd>
                A thirty minute cache TTL with six hour stale-while-revalidate, and concurrent
                background refreshes are collapsed into one.
              </dd>
            </div>
            <div className="rise">
              <dt>One API is refused on purpose</dt>
              <dd>
                <code className="mono">GetCostAndUsageWithResources</code> bills per usage record
                on top of the per-request charge, and on a real account it dominated the running
                cost of the tool. The CUR warehouse does that job instead, locally, for free.
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </section>
  );
}

const LOCAL = [
  {
    h: "Your existing profiles",
    p: <>It reads <code className="mono">~/.aws/credentials</code> and{" "}
       <code className="mono">~/.aws/config</code> directly, and the picker mirrors{" "}
       <code className="mono">aws configure list-profiles</code>. SSO profiles work once{" "}
       <code className="mono">aws sso login</code> has run.</>,
  },
  {
    h: "Read-only against AWS",
    p: <><code className="mono">ReadOnlyAccess</code> is sufficient, and a least-privilege policy
       is documented per API call in <code className="mono">docs/IAM.md</code> if you would
       rather grant less.</>,
  },
  {
    h: "Loopback, or a token",
    p: <>It binds <code className="mono">127.0.0.1</code> and nothing else by default. Any other
       bind requires <code className="mono">SPENDSLICER_AUTH_TOKEN</code>, because an open port
       here is a financial exposure and not only a data one.</>,
  },
  {
    h: "The desktop build too",
    p: <>The native macOS and Windows builds bind an ephemeral loopback port and mint a fresh
       auth token on every launch.</>,
  },
];

function LocalSection() {
  return (
    <section id="local" className="lp-sect sect-rule">
      <div className="wrap">
        <div className="head-block rise">
          <h2>Nothing leaves the machine.</h2>
          <p className="lede">
            No account linking, no agent, no telemetry. Every AWS call is made from your machine
            with your own credentials, and no cost data ever goes anywhere else.
          </p>
        </div>
        <div className="plain">
          {LOCAL.map((x) => (
            <div className="rise" key={x.h}>
              <h3>{x.h}</h3>
              <p>{x.p}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Cmd({ children, copy }) {
  const done = useRef(null);
  const onClick = async (e) => {
    const btn = e.currentTarget;
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("no clipboard");
      await navigator.clipboard.writeText(copy);
      btn.dataset.state = "done";
    } catch {
      btn.dataset.state = "fail";
    }
    clearTimeout(done.current);
    done.current = setTimeout(() => { delete btn.dataset.state; }, 1600);
  };
  useEffect(() => () => clearTimeout(done.current), []);

  return (
    <div className="cmd">
      <code>{children}</code>
      <button className="cmd-copy" type="button" onClick={onClick}
              aria-label={`Copy: ${copy}`}>
        <span className="cmd-copy-idle" aria-hidden="true">Copy</span>
        <span className="cmd-copy-done" aria-hidden="true">Copied</span>
        <span className="cmd-copy-fail" aria-hidden="true">Failed</span>
      </button>
    </div>
  );
}

function InstallSection() {
  return (
    <section id="install" className="lp-sect sect-rule">
      <div className="wrap">
        <div className="head-block rise">
          <h2>Install</h2>
          <p className="lede">Three routes in. All of them run the same server on your own machine.</p>
        </div>

        <div className="routes">
          <div className="route route-wide rise">
            <h3>pip</h3>
            <p>The dashboard bundle ships inside the wheel, so Node.js is not required to run it.</p>
            <Cmd copy={'pip install "spendslicer[web,cur]"'}>pip install "spendslicer[web,cur]"</Cmd>
            <Cmd copy="spendslicer-web">spendslicer-web</Cmd>
            <p className="route-note">
              Then open <code className="mono">http://127.0.0.1:8080/app</code>. Requires Python
              3.10 or newer.
            </p>
          </div>

          <div className="route rise">
            <h3>Desktop app</h3>
            <p>A native build for macOS and Windows, with no Python installed on your machine.</p>
            <p style={{ marginTop: 18 }}>
              <a className="lp-btn lp-btn-quiet lp-btn-sm" href={`${REPO}/releases`}>Releases</a>
            </p>
            <p className="route-note">
              These builds are not code-signed, so macOS will claim the app is damaged and Windows
              SmartScreen will warn. <a href={DOC("docs/DESKTOP.md")}>docs/DESKTOP.md</a> has the
              one line fix for each.
            </p>
          </div>

          <div className="route rise">
            <h3>From source</h3>
            <p>The script creates a virtualenv, installs the web and cur extras, and starts the server.</p>
            <Cmd copy={`git clone ${REPO}.git`}>git clone {REPO}.git</Cmd>
            <Cmd copy="cd spendslicer && ./run.sh">cd spendslicer && ./run.sh</Cmd>
            <p className="route-note">On Windows, <code className="mono">run.bat</code>.</p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* Limits section — hidden for the 1.0.0 launch, kept for when it returns.
   Re-enable by uncommenting this block, the <LimitsSection /> render in App,
   and the #limits nav link. Everything below is still accurate.

const LIMITS = [
  {
    t: "PDF export is Latin-1 only",
    d: <>The PDF uses the core PDF fonts, so a resource name in CJK, Cyrillic or emoji
       renders as <code className="mono">?</code>. CSV and JSON carry those rows as UTF-8.</>,
  },
  {
    t: "Named-resource coverage is fifteen services",
    d: <>EC2, EBS, RDS, S3, ELB, Elastic IP, Lambda, DynamoDB, NAT Gateway, ElastiCache,
       ECR, EFS, Secrets Manager, CloudFront and Route 53 — with no setup. Enable the CUR
       warehouse and every service AWS puts a resource ID on gets named. Anything still
       unnamed appears in the service totals, which are exact.</>,
  },
  {
    t: "The fallback price table is one region",
    d: <>It carries <code className="mono">ap-south-1</code> rates only. Other regions fall
       through to the live Pricing API.</>,
  },
  {
    t: "Desktop builds are not code-signed",
    d: <>Gatekeeper and SmartScreen will both warn.{" "}
       <a href={DOC("docs/DESKTOP.md")}>docs/DESKTOP.md</a> has the fix, and instructions for
       building it yourself if you would rather not trust a binary.</>,
  },
  {
    t: "Costs are pre-credit gross",
    d: <>Matching what the AWS Billing console shows by default. Credits are not deducted.</>,
  },
  {
    t: "Per-resource attribution is still moving",
    d: <>The CUR accuracy model is the part of this tool most likely to change between releases.
       v1.0.0.</>,
  },
];

function LimitsSection() {
  return (
    <section id="limits" className="lp-sect sect-rule">
      <div className="wrap">
        <div className="head-block rise">
          <h2>What does not work yet.</h2>
          <p className="lede">
            Listed here for the same reason the README lists them. A limitation you only discover
            after installing has already wasted your afternoon.
          </p>
        </div>
        <dl className="limits">
          {LIMITS.map((x) => (
            <div className="rise" key={x.t}>
              <dt>{x.t}</dt>
              <dd>{x.d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
*/

const DOCS = [
  ["Architecture", "docs/ARCHITECTURE.md"],
  ["Configuration", "docs/CONFIGURATION.md"],
  ["IAM policy", "docs/IAM.md"],
  ["CUR warehouse", "docs/CUR.md"],
  ["Desktop builds", "docs/DESKTOP.md"],
];

function Foot() {
  return (
    <footer className="foot">
      <div className="wrap">
        <div className="foot-grid">
          <div>
            <Wordmark />
            <p className="foot-note">
              Self-hosted AWS cost visibility. MIT licensed, and every number says where it
              came from.
            </p>
          </div>
          <div>
            <h3>Documentation</h3>
            <ul>{DOCS.map(([label, f]) => (
              <li key={f}><a href={DOC(f)}>{label}</a></li>
            ))}</ul>
          </div>
          <div>
            <h3>Project</h3>
            <ul>
              <li><a href={REPO}>GitHub</a></li>
              <li><a href={`${REPO}/releases`}>Releases</a></li>
              <li><a href={DOC("CHANGELOG.md")}>Changelog</a></li>
              <li><a href={DOC("CONTRIBUTING.md")}>Contributing</a></li>
              <li><a href={DOC("SECURITY.md")}>Security</a></li>
            </ul>
          </div>
        </div>
        <p className="foot-base">
          <span>MIT licensed.</span>
          <span>v1.0.0.</span>
          <span>Python 3.10 or newer.</span>
          <span>Figures in the demo are sample data.</span>
        </p>
      </div>
    </footer>
  );
}

export default function App() {
  const root = useReveal();
  return (
    <div ref={root}>
      <a className="skip" href="#main">Skip to content</a>
      <Nav />
      <main id="main">
        <span id="top" />
        <Hero />
        <SurfacesSection />
        <AttributionSection />
        <MeterSection />
        <LocalSection />
        <InstallSection />
        {/* <LimitsSection /> */}
      </main>
      <Foot />
    </div>
  );
}
