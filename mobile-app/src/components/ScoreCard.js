import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { colors, riskOf } from '../theme';

function Gauge({ score, color }) {
  const size = 104;
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.max(0, Math.min(100, score)) / 100);
  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} style={{ transform: [{ rotate: '-90deg' }] }}>
        <Circle cx={size / 2} cy={size / 2} r={radius} stroke="#E9EEF7" strokeWidth={9} fill="none" />
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={color}
          strokeWidth={9}
          fill="none"
          strokeDasharray={`${circumference} ${circumference}`}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </Svg>
      <View style={styles.center} pointerEvents="none">
        <Text style={styles.score}>{score == null ? '-' : score}</Text>
        <Text style={styles.caption}>/100</Text>
      </View>
    </View>
  );
}

export default function ScoreCard({ report }) {
  if (!report || report.score == null) {
    return (
      <View style={styles.card}>
        <Text style={styles.title}>오늘의 안심 점수</Text>
        <Text style={styles.empty}>카메라 분석이 시작되면 점수가 표시됩니다.</Text>
      </View>
    );
  }
  const risk = riskOf(report.risk_level);
  const factors = ((report.factors && report.factors.items) || []).slice(0, 3);
  return (
    <View style={styles.card}>
      <Gauge score={report.score} color={risk.color} />
      <View style={styles.side}>
        <Text style={styles.title}>오늘의 안심 점수</Text>
        <View style={[styles.badge, { backgroundColor: risk.bg }]}>
          <View style={[styles.dot, { backgroundColor: risk.color }]} />
          <Text style={[styles.badgeText, { color: risk.color }]}>{report.risk_label || risk.label} 단계</Text>
        </View>
        {factors.length ? (
          factors.map((factor, index) => (
            <Text key={index} style={styles.factor}>
              · {factor.detail || factor.label}
            </Text>
          ))
        ) : (
          <Text style={styles.factor}>· 평소와 비슷한 하루였습니다</Text>
        )}
        <Text style={styles.meta}>참고용 지표 · 의료 진단 아님</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    backgroundColor: colors.card,
    borderRadius: 20,
    padding: 16,
    marginBottom: 12,
    alignItems: 'center',
  },
  center: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  score: { fontSize: 30, fontWeight: '800', color: colors.navy },
  caption: { fontSize: 11, color: colors.muted, marginTop: -2 },
  side: { flex: 1, marginLeft: 14 },
  title: { fontSize: 12, fontWeight: '700', color: colors.muted },
  badge: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 99, marginTop: 6 },
  dot: { width: 6, height: 6, borderRadius: 3, marginRight: 5 },
  badgeText: { fontSize: 12, fontWeight: '800' },
  factor: { fontSize: 11, color: colors.muted, marginTop: 4, lineHeight: 15 },
  meta: { fontSize: 10, color: '#94A1B8', marginTop: 6 },
  empty: { fontSize: 12, color: colors.muted, marginTop: 6 },
});
