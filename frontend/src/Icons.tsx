// Ally's icon set. Drawn, one library, 1.7 stroke on a 24 grid, currentColor
// throughout. Decorative by default: the control beside each one carries the
// accessible name, so these are aria-hidden.

import type { SVGProps } from 'react'

type P = SVGProps<SVGSVGElement> & { size?: number }

const wrap = (children: React.ReactNode) => (p: P) => {
  const { size = 16, ...rest } = p
  return (
    <svg
      {...rest}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

export const Play = wrap(<path d="M8 5.2v13.6L19 12 8 5.2Z" />)
export const Pulse = wrap(<path d="M3 12h3.6l2.4-6 3.8 12 2.6-6H21" />)
export const Layers = wrap(
  <>
    <path d="m12 3 8.5 4.6L12 12.2 3.5 7.6 12 3Z" />
    <path d="m3.5 12.4 8.5 4.6 8.5-4.6" />
  </>,
)
export const Flag = wrap(
  <>
    <path d="M5.5 21V4.2" />
    <path d="M5.5 4.8h11l-2 3.4 2 3.4h-11" />
  </>,
)
export const Branch = wrap(
  <>
    <circle cx="6.5" cy="5.5" r="2.1" />
    <circle cx="6.5" cy="18.5" r="2.1" />
    <circle cx="17.5" cy="18.5" r="2.1" />
    <path d="M6.5 7.6v8.8M17.5 16.4V9.8A2.3 2.3 0 0 0 15.2 7.5h-3" />
  </>,
)
export const Check = wrap(<path d="m4.8 12.4 4.6 4.6L19.4 7" />)
export const Alert = wrap(
  <>
    <path d="M12 4.4 2.9 20h18.2L12 4.4Z" />
    <path d="M12 10.2v4.1M12 17.3h.01" />
  </>,
)
export const Clock = wrap(
  <>
    <circle cx="12" cy="12" r="8.4" />
    <path d="M12 7.5V12l3.1 2" />
  </>,
)
export const Link = wrap(
  <>
    <path d="M14 4.5h5.5V10" />
    <path d="M19.5 4.5 11 13" />
    <path d="M17.6 14.4v4.6a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5V7.9A1.5 1.5 0 0 1 5 6.4h4.6" />
  </>,
)
export const Code = wrap(<path d="M9 7.4 4.6 12 9 16.6M15 7.4 19.4 12 15 16.6" />)
export const Back = wrap(<path d="M19 12H5.5M11 5.5 4.6 12l6.4 6.5" />)
