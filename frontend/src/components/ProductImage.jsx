const hash = (s) => {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
};

export default function ProductImage({ name = '', className = 'h-40 w-full' }) {
  const h = hash(name) % 360;
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
  return (
    <svg viewBox="0 0 200 140" className={`${className} rounded-md`} role="img" aria-label={name} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`g${h}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={`hsl(${h},70%,60%)`} />
          <stop offset="1" stopColor={`hsl(${(h + 50) % 360},70%,40%)`} />
        </linearGradient>
      </defs>
      <rect width="200" height="140" fill={`url(#g${h})`} />
      <text x="100" y="82" textAnchor="middle" fontSize="44" fontWeight="700" fill="white" fontFamily="sans-serif">{initials}</text>
    </svg>
  );
}
