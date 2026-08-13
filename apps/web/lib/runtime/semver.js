// Gate C §8.2 — strict SemVer 2.0.0 comparison.
//
// Implemented here (instead of a string compare) so that 0.10.0 > 0.9.0 is
// judged correctly. Kept dependency-free and fully unit-tested; build
// metadata never participates in precedence.
const SEMVER = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/;

function parsePrerelease(value) {
  if (!value) return null;
  return value.split('.');
}

function compareIdentifiers(a, b) {
  const aNum = /^\d+$/.test(a);
  const bNum = /^\d+$/.test(b);
  if (aNum && bNum) {
    const diff = BigInt(a) - BigInt(b);
    return diff === 0n ? 0 : diff > 0n ? 1 : -1;
  }
  if (aNum) return -1; // numeric identifiers always sort lower
  if (bNum) return 1;
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function comparePrerelease(a, b) {
  const pa = parsePrerelease(a);
  const pb = parsePrerelease(b);
  if (pa === null && pb === null) return 0;
  if (pa === null) return 1; // a has no prerelease => a is greater
  if (pb === null) return -1;
  const length = Math.max(pa.length, pb.length);
  for (let i = 0; i < length; i += 1) {
    if (pa[i] === undefined) return -1;
    if (pb[i] === undefined) return 1;
    const cmp = compareIdentifiers(pa[i], pb[i]);
    if (cmp !== 0) return cmp;
  }
  return 0;
}

export function parseVersion(value) {
  if (typeof value !== 'string') throw new Error(`invalid semver: ${String(value)}`);
  const match = SEMVER.exec(value.trim());
  if (!match) throw new Error(`invalid semver: ${value}`);
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] || null,
    build: match[5] || null,
  };
}

// Returns 1 if a > b, 0 if equal, -1 if a < b. Build metadata is ignored.
export function compareVersions(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  if (pa.major !== pb.major) return pa.major > pb.major ? 1 : -1;
  if (pa.minor !== pb.minor) return pa.minor > pb.minor ? 1 : -1;
  if (pa.patch !== pb.patch) return pa.patch > pb.patch ? 1 : -1;
  return comparePrerelease(pa.prerelease, pb.prerelease);
}

export function isAtLeast(candidate, minimum) {
  return compareVersions(candidate, minimum) >= 0;
}
