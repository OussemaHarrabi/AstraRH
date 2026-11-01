/** An arched door with a star above it: the Sidi Bou Said door, and Astra. */
export function Logo({ size = 22, className = "" }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden className={`shrink-0 ${className}`}>
      <rect width="24" height="24" rx="6.500" fill="var(--door)" />
      <path d="M7.500 20v-7.500a4.500 4.500 0 0 1 9 0V20z" fill="#fff" />
      <path d="M12 3l.8 2.200L15 6l-2.200.8L12 9l-.8-2.200L9 6l2.200-.8z" fill="#fff" />
      <circle cx="14.300" cy="15.500" r=".9" fill="var(--door)" />
    </svg>
  );
}
