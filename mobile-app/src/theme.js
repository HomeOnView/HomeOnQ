export const colors = {
  navy: '#0B1F4B',
  navy2: '#14306E',
  ink: '#16223A',
  muted: '#566079',
  line: '#E0E6F0',
  bg: '#EEF2F8',
  card: '#FFFFFF',
  gold: '#E3A62F',
  green: '#1E7B4C',
  greenSoft: '#E6F2EC',
  amber: '#A84D08',
  amberSoft: '#FDF0E2',
  red: '#B42318',
  redSoft: '#FDECEA',
};

export const riskStyles = {
  SAFE: { color: colors.green, bg: colors.greenSoft, label: '안심' },
  WATCH: { color: colors.amber, bg: colors.amberSoft, label: '주의' },
  ALERT: { color: colors.red, bg: colors.redSoft, label: '경계' },
  UNKNOWN: { color: colors.muted, bg: '#EFF2F7', label: '확인 필요' },
};

export function riskOf(level) {
  return riskStyles[level] || riskStyles.UNKNOWN;
}
