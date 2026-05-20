// app.jsx — Root component, routing, Tweaks

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#0E9F6E",
  "page": "dashboard",
  "density": "regular",
  "sidebarCollapsed": false,
  "gradient": true,
  "gradientPalette": "indigo-teal",
  "dark": false
}/*EDITMODE-END*/;

const GRADIENT_PALETTES = {
  'indigo-teal':  { a: '#6E5BFF', b: '#3D2BD6', c: '#11AABE', d: '#0E9F6E' },
  'sunset':       { a: '#FF8A4C', b: '#E0364E', c: '#A24DDD', d: '#3D2BD6' },
  'ocean':        { a: '#3B5BDB', b: '#11AABE', c: '#0E9F6E', d: '#94B344' },
  'monochrome':   { a: '#525252', b: '#1F1F1F', c: '#737373', d: '#A3A3A3' },
};

const ACCENTS = [
  { val: '#0E9F6E', soft: '#E6F4EE', ink: '#0A6F4D', glow: 'rgba(14,159,110,0.14)' },
  { val: '#3B5BDB', soft: '#EAEEFB', ink: '#2540B6', glow: 'rgba(59,91,219,0.14)' },
  { val: '#7A5AE0', soft: '#EFEAFB', ink: '#5B3FC0', glow: 'rgba(122,90,224,0.14)' },
  { val: '#DF7032', soft: '#FCEDDF', ink: '#A65420', glow: 'rgba(223,112,50,0.14)' },
];

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  const [page, setPage] = React.useState(t.page || 'dashboard');
  const [collapsed, setCollapsed] = React.useState(!!t.sidebarCollapsed);
  const [profile, setProfile] = React.useState(window.DATA.profiles[0]);
  const [period, setPeriod] = React.useState('mtd');
  const [costMode] = React.useState('Pre-credit');
  const [refreshing, setRefreshing] = React.useState(false);
  const [resourceFilter, setResourceFilter] = React.useState(null);

  // Apply accent
  React.useEffect(() => {
    const a = ACCENTS.find(x => x.val === t.accent) || ACCENTS[0];
    const r = document.documentElement;
    r.style.setProperty('--accent', a.val);
    r.style.setProperty('--accent-soft', a.soft);
    r.style.setProperty('--accent-ink', a.ink);
    r.style.setProperty('--accent-glow', a.glow);
  }, [t.accent]);

  // Apply gradient theme
  React.useEffect(() => {
    document.body.classList.toggle('theme-gradient', !!t.gradient);
  }, [t.gradient]);

  // Apply gradient palette
  React.useEffect(() => {
    const p = GRADIENT_PALETTES[t.gradientPalette] || GRADIENT_PALETTES['indigo-teal'];
    const r = document.documentElement;
    r.style.setProperty('--grad-a', p.a);
    r.style.setProperty('--grad-b', p.b);
    r.style.setProperty('--grad-c', p.c);
    r.style.setProperty('--grad-d', p.d);
  }, [t.gradientPalette]);

  // Apply dark theme
  React.useEffect(() => {
    document.body.classList.toggle('theme-dark', !!t.dark);
  }, [t.dark]);

  // Persist page choice as a tweak default
  React.useEffect(() => { setTweak('page', page); }, [page]);
  React.useEffect(() => { setTweak('sidebarCollapsed', collapsed); }, [collapsed]);

  const onRefresh = () => {
    setRefreshing(true);
    setTimeout(() => setRefreshing(false), 1100);
  };

  const titles = {
    dashboard: 'Dashboard',
    services: 'Services',
    resources: 'Resources',
    trends: 'Trends',
    audit: 'Audit',
    export: 'Export',
  };

  const renderPage = () => {
    switch (page) {
      case 'dashboard': return <Dashboard period={period} profile={profile} />;
      case 'services':  return <Services setPage={setPage} setResourceFilter={setResourceFilter} />;
      case 'resources': return <Resources resourceFilter={resourceFilter} setResourceFilter={setResourceFilter} />;
      case 'trends':    return <Trends />;
      case 'audit':     return <Audit />;
      case 'export':    return <ExportPage profile={profile} period={period} />;
      default: return <Dashboard period={period} profile={profile} />;
    }
  };

  return (
    <div className={'app' + (collapsed ? ' collapsed' : '')}>
      <Sidebar
        page={page} setPage={(p) => { setPage(p); if (p !== 'resources') setResourceFilter(null); }}
        collapsed={collapsed} setCollapsed={setCollapsed}
        profile={profile}
      />
      <div className="main">
        <TopBar
          profile={profile} setProfile={setProfile}
          period={period} setPeriod={setPeriod}
          costMode={costMode}
          refreshing={refreshing} onRefresh={onRefresh}
          profiles={window.DATA.profiles}
          periods={window.DATA.periods}
          dark={t.dark}
          setDark={(v) => setTweak('dark', v)}
        />
        <div className="scroll" key={page}>
          {renderPage()}
        </div>
      </div>

      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakToggle label="Dark mode" value={t.dark}
                     onChange={(v) => setTweak('dark', v)} />
        <TweakColor label="Accent" value={t.accent}
                    options={ACCENTS.map(a => a.val)}
                    onChange={(v) => setTweak('accent', v)} />
        <TweakToggle label="Premium gradient" value={t.gradient}
                     onChange={(v) => setTweak('gradient', v)} />
        <TweakSelect label="Gradient palette" value={t.gradientPalette}
                     options={Object.keys(GRADIENT_PALETTES).map(k => ({ value: k, label: k }))}
                     onChange={(v) => setTweak('gradientPalette', v)} />

        <TweakSection label="Navigation" />
        <TweakSelect label="Page" value={page}
                     options={Object.keys(titles).map(k => ({ value: k, label: titles[k] }))}
                     onChange={setPage} />
        <TweakToggle label="Collapsed sidebar" value={collapsed}
                     onChange={setCollapsed} />

        <TweakSection label="Context" />
        <TweakSelect label="Profile" value={profile.id}
                     options={window.DATA.profiles.map(p => ({ value: p.id, label: `${p.alias} · ${p.account}` }))}
                     onChange={(id) => setProfile(window.DATA.profiles.find(p => p.id === id))} />
        <TweakSelect label="Period" value={period}
                     options={window.DATA.periods.map(p => ({ value: p.id, label: p.label }))}
                     onChange={setPeriod} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
