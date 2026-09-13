// Drawn icons, one library, one stroke weight. Emoji standing in for an icon
// system is the cheapest tell that a page was assembled rather than built, and
// it also reads differently on every platform, which a product that audits
// accessibility cannot afford.
//
// 1.6 stroke, round caps and joins, 24-unit grid, currentColor throughout so a
// token change carries. Every icon is decorative here: the control beside it
// always carries the accessible name, so these are aria-hidden.

import type { SVGProps } from 'react'

const base = {
  width: 16,
  height: 16,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  focusable: false,
}

type P = SVGProps<SVGSVGElement> & { size?: number }
const svg = (d: React.ReactNode) => (p: P) => {
  const { size, ...rest } = p
  return (
    <svg {...base} {...rest} width={size ?? base.width} height={size ?? base.height}>
      {d}
    </svg>
  )
}

export const IconKeyboard = svg(
  <>
    <rect x="2" y="6" width="20" height="12" rx="2.5" />
    <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8" />
  </>,
)

export const IconPlay = svg(<path d="M7 4.5v15l13-7.5-13-7.5Z" />)

export const IconTarget = svg(
  <>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="3.5" />
  </>,
)

export const IconGitBranch = svg(
  <>
    <circle cx="7" cy="5" r="2.2" />
    <circle cx="7" cy="19" r="2.2" />
    <circle cx="17" cy="9" r="2.2" />
    <path d="M7 7.2v9.6M17 11.2c0 3-3.2 3.6-6 4.4" />
  </>,
)

export const IconPullRequest = svg(
  <>
    <circle cx="6.5" cy="5" r="2.2" />
    <circle cx="6.5" cy="19" r="2.2" />
    <circle cx="17.5" cy="19" r="2.2" />
    <path d="M6.5 7.2v9.6M17.5 16.8V9.5A2.5 2.5 0 0 0 15 7h-3.2M13.6 5 11.8 7l1.8 2" />
  </>,
)

export const IconChart = svg(
  <>
    <path d="M4 20h16" />
    <path d="M7 20v-6M12 20V6M17 20v-9" />
  </>,
)

export const IconLoop = svg(
  <>
    <path d="M4 12a8 8 0 0 1 13.7-5.6M20 12a8 8 0 0 1-13.7 5.6" />
    <path d="M18 3v3.6h-3.6M6 21v-3.6h3.6" />
  </>,
)

export const IconCheck = svg(<path d="M4.5 12.8l4.6 4.6L19.5 7" />)

export const IconAlert = svg(
  <>
    <path d="M12 4.2 2.8 20h18.4L12 4.2Z" />
    <path d="M12 10v4.2M12 17.2h.01" />
  </>,
)

export const IconInfo = svg(
  <>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11v5.2M12 7.8h.01" />
  </>,
)

export const IconClock = svg(
  <>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.4V12l3.2 2" />
  </>,
)

export const IconSun = svg(
  <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4 17 7M7 17l-1.6 1.6" />
  </>,
)

export const IconMoon = svg(<path d="M20 13.4A8.4 8.4 0 1 1 10.6 4a6.8 6.8 0 0 0 9.4 9.4Z" />)

export const IconExternal = svg(
  <>
    <path d="M14 4h6v6" />
    <path d="M20 4l-8.5 8.5" />
    <path d="M18 14.5V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V7.5A1.5 1.5 0 0 1 5 6h4.5" />
  </>,
)

export const IconCode = svg(
  <>
    <path d="M9 7.5 4.5 12 9 16.5M15 7.5 19.5 12 15 16.5" />
  </>,
)
