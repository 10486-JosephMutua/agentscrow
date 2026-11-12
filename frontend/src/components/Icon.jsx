// A tiny inline icon set (24x24, stroke-based) so the UI needs no icon dependency and no network requests.
const PATHS = {
  check: ['M20 6 9 17l-5-5'],
  x: ['M18 6 6 18', 'M6 6l12 12'],
  lock: ['M7 11V8a5 5 0 0 1 10 0v3', 'M5 11h14v10H5z'],
  clock: ['M12 7v5l3 2', 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z'],
  alert: ['M12 9v4', 'M12 17h.01', 'M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'],
  shield: ['M12 3 5 6v5c0 4.5 3 7.7 7 9 4-1.3 7-4.5 7-9V6l-7-3z'],
  code: ['m8 8-4 4 4 4', 'm16 8 4 4-4 4'],
  copy: ['M9 9h10v10H9z', 'M5 15V5h10'],
  arrow: ['M5 12h14', 'm13 6 6 6-6 6'],
  bank: ['M3 10 12 4l9 6', 'M5 10v8', 'M9 10v8', 'M15 10v8', 'M19 10v8', 'M3 20h18'],
  refresh: ['M20 11a8 8 0 0 0-14-4L4 9', 'M4 4v5h5', 'M4 13a8 8 0 0 0 14 4l2-2', 'M20 20v-5h-5'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21a8 8 0 0 1 16 0'],
  doc: ['M7 3h8l4 4v14H7z', 'M15 3v4h4', 'M10 13h6', 'M10 17h6'],
  scale: ['M12 3v18', 'M5 7h14', 'M5 7l-3 7a3 3 0 0 0 6 0L5 7z', 'M19 7l-3 7a3 3 0 0 0 6 0l-3-7z'],
  bolt: ['M13 2 4 14h7l-1 8 9-12h-7l1-8z'],
  menu: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
  search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'm21 21-4.3-4.3'],
  download: ['M12 4v11', 'm7 11 5 5 5-5', 'M5 20h14'],
  terminal: ['M4 5h16v14H4z', 'm8 10 3 2-3 2', 'M13 15h3'],
  plus: ['M12 5v14', 'M5 12h14'],
  print: ['M7 8V3h10v5', 'M6 17H4v-7h16v7h-2', 'M7 14h10v7H7z'],
  dot: ['M12 12h.01'],
}

export default function Icon({ name, className = 'h-4 w-4', title }) {
  const paths = PATHS[name] ?? PATHS.dot
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      {paths.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}
