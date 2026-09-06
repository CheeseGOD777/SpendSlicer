/* Authored icon set — one family, 1.5px stroke on a 20px box, currentColor.
   No emoji, no unicode glyphs, no icon dependency. */

const S = ({ children, size = 18, ...rest }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 20 20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
    {...rest}
  >
    {children}
  </svg>
);

/* Board — the departure board itself: a headline figure over queued rows */
export const IconBoard = (p) => (
  <S {...p}>
    <rect x="2.5" y="3" width="15" height="14" rx="1.5" />
    <path d="M5.5 7h5M5.5 10.5h9M5.5 13.5h9" />
  </S>
);

/* Services — stacked classes of service */
export const IconServices = (p) => (
  <S {...p}>
    <path d="M10 2.75 17.5 6.5 10 10.25 2.5 6.5z" />
    <path d="M2.5 10 10 13.75 17.5 10" />
    <path d="M2.5 13.5 10 17.25 17.5 13.5" />
  </S>
);

/* Resources — named machines */
export const IconResources = (p) => (
  <S {...p}>
    <rect x="2.5" y="3.25" width="15" height="5.5" rx="1.5" />
    <rect x="2.5" y="11.25" width="15" height="5.5" rx="1.5" />
    <path d="M5.5 6h.01M5.5 14h.01" />
  </S>
);

/* Audit — the disruption notice */
export const IconAudit = (p) => (
  <S {...p}>
    <path d="M10 2.75 18 16.5H2z" />
    <path d="M10 8v3.5M10 14h.01" />
  </S>
);

/* Export — issue a copy */
export const IconExport = (p) => (
  <S {...p}>
    <path d="M10 2.75v9" />
    <path d="M6.5 8.5 10 12l3.5-3.5" />
    <path d="M3.25 13.5v2.25a1.5 1.5 0 0 0 1.5 1.5h10.5a1.5 1.5 0 0 0 1.5-1.5V13.5" />
  </S>
);

export const IconChevron = (p) => (
  <S {...p}><path d="M7.5 4.5 13 10l-5.5 5.5" /></S>
);
export const IconChevronDown = (p) => (
  <S {...p}><path d="M4.5 7.5 10 13l5.5-5.5" /></S>
);
export const IconArrowUp = (p) => (
  <S {...p}><path d="M10 15.5v-11" /><path d="M5.5 9 10 4.5 14.5 9" /></S>
);
export const IconArrowDown = (p) => (
  <S {...p}><path d="M10 4.5v11" /><path d="M14.5 11 10 15.5 5.5 11" /></S>
);
export const IconMinus = (p) => (<S {...p}><path d="M5 10h10" /></S>);
export const IconCheck = (p) => (<S {...p}><path d="M4.5 10.5 8 14l7.5-8" /></S>);
export const IconCopy = (p) => (
  <S {...p}>
    <rect x="7" y="7" width="10" height="10" rx="1.5" />
    <path d="M13 4.5H4.5A1.5 1.5 0 0 0 3 6v8.5" />
  </S>
);
export const IconAlert = (p) => (
  <S {...p}><circle cx="10" cy="10" r="7.25" /><path d="M10 6.25v4.5M10 13.5h.01" /></S>
);
export const IconCoin = (p) => (
  <S {...p}><circle cx="10" cy="10" r="7.25" /><path d="M10 6v8M12.25 7.75H8.75a1.5 1.5 0 0 0 0 3h2.5a1.5 1.5 0 0 1 0 3H7.75" /></S>
);
export const IconMenu = (p) => (
  <S {...p}><path d="M3.5 6h13M3.5 10h13M3.5 14h13" /></S>
);
export const IconSearch = (p) => (
  <S {...p}><circle cx="8.75" cy="8.75" r="5.25" /><path d="M12.75 12.75 17 17" /></S>
);

/* The SpendSlicer mark: a board figure sliced. Drawn, not a monogram. */
export const Mark = ({ size = 19 }) => (
  <svg width={size} height={size} viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
    <rect x="2" y="3" width="16" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="1.6" />
    <path d="M5.5 12.5 9 7l2.5 4L14.5 6.5" stroke="currentColor" strokeWidth="1.6"
          strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
